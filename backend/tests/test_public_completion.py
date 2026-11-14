import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from security.public_completion import (
    CompletionUnavailable, CompletionNotSubmitted, CompletionCancelledBeforeSend,
    PublicCompletionClient, REQUEST_BYTES, RESPONSE_BYTES,
)


class PublicCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'dispatcher.sock'
        self.token = 'a' * 64
        self.reservation = 'b' * 64
        self.requests = []
        self.mode = 'reply'
        self.received = asyncio.Event()
        self.closed = asyncio.Event()
        self.connections = set()
        self.reply = self.encode(self.valid_response())
        self.server = await asyncio.start_unix_server(self.handle, path=self.path, limit=REQUEST_BYTES)
        self.client = PublicCompletionClient(self.path, self.token, timeout=1)

    def valid_response(self):
        return {'version': 1, 'status': 'complete', 'reservation_id': self.reservation,
                'answer': '공개 답변', 'citation_ids': ['D1', 'D4']}

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False).encode() + b'\n'

    async def handle(self, reader, writer):
        self.connections.add(writer)
        try:
            data = await reader.readuntil(b'\n')
            self.requests.append(json.loads(data))
            self.received.set()
            if self.mode == 'hold':
                await reader.read()
            else:
                writer.write(self.reply)
                await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.connections.discard(writer)
            self.closed.set()

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        for writer in tuple(self.connections):
            writer.close()
            await writer.wait_closed()

    async def complete(self, **overrides):
        args = dict(reservation_id=self.reservation, question='question-canary',
                    context='approved context', history=[{'role': 'user', 'content': 'hello'}])
        args.update(overrides)
        return await self.client.complete(**args)

    async def unavailable(self, expected=CompletionUnavailable, **overrides):
        with self.assertRaises(expected) as failure:
            await self.complete(**overrides)
        self.assertIs(type(failure.exception), expected)
        self.assertEqual(str(failure.exception), 'Public completion unavailable')
        self.assertNotIn(self.token, str(failure.exception))
        self.assertNotIn('question-canary', str(failure.exception))
        self.assertTrue(failure.exception.__suppress_context__)

    async def test_success_and_wire_contract(self):
        result = await self.complete()
        self.assertEqual(result, {'answer': '공개 답변', 'citation_ids': ['D1', 'D4']})
        self.assertEqual(self.requests, [{'version': 1, 'token': self.token, 'operation': 'complete',
                         'reservation_id': self.reservation, 'question': 'question-canary',
                         'context': 'approved context', 'history': [{'role': 'user', 'content': 'hello'}]}])
        self.assertNotIn(self.token, repr(self.client))

    async def test_invalid_response_contract(self):
        invalid = [[], {}, {**self.valid_response(), 'reservation_id': 'c' * 64},
                   {**self.valid_response(), 'version': True},
                   {**self.valid_response(), 'status': 'failed'},
                   {**self.valid_response(), 'debug': 'question-canary'},
                   {**self.valid_response(), 'answer': '한' * 5462},
                   {**self.valid_response(), 'answer': ''},
                   {**self.valid_response(), 'answer': '\ud800'}]
        for citations in ([], ['D1', 'D1'], ['D5'], ['D1', {}], 'D1', ['D1'] * 5):
            invalid.append({**self.valid_response(), 'citation_ids': citations})
        for response in invalid:
            self.reply = json.dumps(response).encode() + b'\n'
            await self.unavailable()

    async def test_malformed_oversize_and_unterminated_response(self):
        for reply in (b'question-canary\n', b'\xff\n', self.encode(self.valid_response()).rstrip(b'\n'),
                      b'x' * RESPONSE_BYTES + b'\n', b'x' * (RESPONSE_BYTES + 1),
                      b'{"version":1,"version":1}\n'):
            self.reply = reply
            await self.unavailable()

    async def test_timeout_closes_socket_without_retry(self):
        self.mode = 'hold'
        self.client = PublicCompletionClient(self.path, self.token, timeout=0.05)
        await self.unavailable()
        await asyncio.wait_for(self.closed.wait(), 1)
        self.assertEqual(len(self.requests), 1)

    async def test_cancel_propagates_and_closes_socket_without_retry(self):
        self.mode = 'hold'
        task = asyncio.create_task(self.complete())
        await asyncio.wait_for(self.received.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError) as failure:
            await task
        self.assertIs(type(failure.exception), asyncio.CancelledError)
        await asyncio.wait_for(self.closed.wait(), 1)
        self.assertEqual(len(self.requests), 1)

    async def test_invalid_and_oversize_request_never_connects(self):
        for kwargs in ({'reservation_id': 'wrong'}, {'question': 'x' * REQUEST_BYTES},
                       {'context': '한' * REQUEST_BYTES}, {'question': '\ud800'},
                       {'history': [float('nan')]}, {'history': object()}):
            await self.unavailable(expected=CompletionNotSubmitted, **kwargs)
        self.assertEqual(self.requests, [])

    async def test_missing_socket_is_fixed_failure(self):
        self.client = PublicCompletionClient(self.path.with_name('missing.sock'), self.token)
        await self.unavailable(expected=CompletionNotSubmitted)

    async def test_cancel_before_connect_is_known_not_submitted(self):
        connecting = asyncio.Event()

        async def stalled_connect(*args, **kwargs):
            connecting.set()
            await asyncio.Event().wait()

        with patch('security.public_completion.asyncio.open_unix_connection', stalled_connect):
            task = asyncio.create_task(self.complete())
            await asyncio.wait_for(connecting.wait(), 1)
            task.cancel()
            with self.assertRaises(CompletionCancelledBeforeSend):
                await task
        self.assertEqual(self.requests, [])

    async def test_timeout_before_connect_is_known_not_submitted(self):
        async def stalled_connect(*args, **kwargs):
            await asyncio.Event().wait()

        self.client = PublicCompletionClient(self.path, self.token, timeout=0.05)
        with patch('security.public_completion.asyncio.open_unix_connection', stalled_connect):
            await self.unavailable(expected=CompletionNotSubmitted)
        self.assertEqual(self.requests, [])

    async def test_write_failure_is_uncertain_and_never_refundable(self):
        writer = Mock()
        writer.write.side_effect = OSError('question-canary')

        async def connected(*args, **kwargs):
            return Mock(), writer

        with patch('security.public_completion.asyncio.open_unix_connection', connected):
            await self.unavailable()
        writer.close.assert_called_once()
        writer.transport.abort.assert_called_once()

    def test_invalid_configuration_does_not_echo_values(self):
        for path, token, timeout in ((Path('relative'), self.token, 1),
                                     (self.path, 'token-canary', 1),
                                     (self.path, self.token, 0),
                                     (self.path, self.token, float('inf'))):
            with self.assertRaises(ValueError) as failure:
                PublicCompletionClient(path, token, timeout)
            self.assertNotIn('token-canary', str(failure.exception))


if __name__ == '__main__':
    unittest.main()
