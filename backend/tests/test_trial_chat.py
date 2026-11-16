import asyncio
from pathlib import Path
import sqlite3
import socket
import tempfile
import threading
import unittest

from security.trial_chat import IncompleteExecution, TrialChat
from security.public_completion import PublicCompletionClient, CompletionNotSubmitted
from security.trial_quota import TrialPolicy, TrialQuota, QuotaExceeded


class Context:
    def model_input(self):
        return 'public evidence only'


class Evidence:
    def gather(self, query, document_ids):
        return Context()

    def finalize(self, context, answer, citation_ids):
        return {'answer': answer, 'citations': [], 'partial': False}


class TrialChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'trial.sqlite'
        self.policy = TrialPolicy(per_network_day_limit=10, global_day_limit=10, max_in_flight=1)
        self.quota = TrialQuota(self.path, policy=self.policy)
        self.quota.initialize()
        self.evidence = Evidence()
        self.calls = []
        self.mode = 'success'
        self.entered = asyncio.Event()

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        reservation = kwargs['reservation_id']
        if self.mode == 'unverified':
            return {'answer': 'answer canary', 'citation_ids': ['D1']}
        self.assertTrue(self.quota.mark_started(reservation))
        self.entered.set()
        if self.mode == 'disconnect':
            raise ConnectionError('transport lost')
        if self.mode == 'cancel':
            await asyncio.Event().wait()
        self.quota.finish(reservation)
        return {'answer': 'answer canary', 'citation_ids': ['D1']}

    async def answer(self):
        return await TrialChat(self.quota, self.evidence, self).answer(
            actor_hash='a' * 64, network_hash='b' * 64, question='question canary')

    async def test_success_counts_once_without_persisting_content(self):
        result = await self.answer()
        self.assertEqual(result['remaining'], 2)
        reservation = self.calls[0]['reservation_id']
        self.assertEqual(self.quota.state(reservation), 'finished')
        self.assertFalse(self.quota.finish(reservation))
        self.assertEqual(self.quota.remaining('a' * 64), 2)
        with sqlite3.connect(self.path) as conn:
            dump = '\n'.join(conn.iterdump())
        for value in ('question canary', 'answer canary', 'public evidence only'):
            self.assertNotIn(value, dump)

    async def test_gather_failure_refunds_without_dispatch(self):
        def fail(*args):
            raise ValueError('no evidence')
        self.evidence.gather = fail
        with self.assertRaises(ValueError):
            await self.answer()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.quota.remaining('a' * 64), 3)

    async def test_transport_failure_does_not_release_running_child(self):
        self.mode = 'disconnect'
        with self.assertRaises(ConnectionError):
            await self.answer()
        self.assertEqual(self.quota.state(self.calls[0]['reservation_id']), 'running')
        recreated = TrialQuota(self.path, policy=self.policy)
        self.assertEqual(recreated.remaining('a' * 64), 2)
        with self.assertRaises(QuotaExceeded):
            recreated.reserve(actor_hash='c' * 64, network_hash='b' * 64)

    async def test_cancel_during_gather_refunds_and_never_dispatches(self):
        entered, stopped = threading.Event(), threading.Event()
        def gather(*args):
            entered.set()
            stopped.wait(3)
            return Context()
        self.evidence.gather = gather
        task = asyncio.create_task(self.answer())
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(self.quota.remaining('a' * 64), 2)
            with self.assertRaises(QuotaExceeded):
                self.quota.reserve(actor_hash='c' * 64, network_hash='b' * 64)
            self.assertEqual(self.calls, [])
        finally:
            stopped.set()
        async def wait_refund():
            while self.quota.remaining('a' * 64) != 3:
                await asyncio.sleep(0.001)
        await asyncio.wait_for(wait_refund(), 3)
        self.assertEqual(self.calls, [])

    async def test_serialization_failure_before_dispatch_refunds(self):
        class BadContext:
            def model_input(self):
                raise ValueError('cannot serialize')
        self.evidence.gather = lambda *args: BadContext()
        with self.assertRaises(ValueError):
            await self.answer()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.quota.remaining('a' * 64), 3)

    async def test_cancellation_leaves_slot_until_dispatcher_confirms_stop(self):
        self.mode = 'cancel'
        task = asyncio.create_task(self.answer())
        await asyncio.wait_for(self.entered.wait(), 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        reservation = self.calls[0]['reservation_id']
        self.assertEqual(self.quota.state(reservation), 'running')
        with self.assertRaises(QuotaExceeded):
            self.quota.reserve(actor_hash='c' * 64, network_hash='b' * 64)
        # Simulated trusted dispatcher notification; actual process-stop proof
        # belongs to the separate container integration test, not this fixture.
        self.quota.finish(reservation)
        self.assertEqual(self.quota.remaining('a' * 64), 2)
        self.quota.reserve(actor_hash='c' * 64, network_hash='b' * 64)

    async def test_result_without_verified_finish_rejected(self):
        self.mode = 'unverified'
        with self.assertRaises(IncompleteExecution):
            await self.answer()
        self.assertEqual(self.quota.state(self.calls[0]['reservation_id']), 'reserved')

    async def test_unreachable_dispatcher_refunds_and_can_recover(self):
        socket_path = Path(self.tmp.name) / 'stale.sock'
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(str(socket_path))
        client = PublicCompletionClient(socket_path, 'f' * 64)
        chat = TrialChat(self.quota, self.evidence, client)
        for _ in range(4):
            with self.assertRaises(CompletionNotSubmitted):
                await chat.answer(actor_hash='a' * 64, network_hash='b' * 64, question='canary')
            self.assertEqual(self.quota.remaining('a' * 64), 3)
        self.assertEqual((await self.answer())['remaining'], 2)

    async def test_revoked_evidence_discards_answer_without_refund(self):
        def revoked(*args):
            raise ValueError('evidence changed')
        self.evidence.finalize = revoked
        with self.assertRaises(ValueError):
            await self.answer()
        self.assertEqual(self.quota.state(self.calls[0]['reservation_id']), 'finished')
        self.assertEqual(self.quota.remaining('a' * 64), 2)


if __name__ == '__main__':
    unittest.main()
