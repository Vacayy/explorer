"""Admission/evidence orchestration; no transcript persistence or provider secrets.

The completion adapter is a trusted dispatcher boundary. Once complete() is
entered it owns reservation reconciliation even if this coroutine is cancelled.
Only the dispatcher may start/finish, after proving its child has stopped.
"""
import asyncio


class IncompleteExecution(Exception):
    """No verified terminal execution; do not expose an answer or refund."""


class TrialChat:
    def __init__(self, quota, evidence, completion):
        self.quota = quota
        self.evidence = evidence
        self.completion = completion

    async def answer(self, *, actor_hash, network_hash, question,
                     history=(), query='', document_ids=()):
        reservation = self.quota.reserve(actor_hash=actor_hash, network_hash=network_hash)
        async def prepare():
            context = await asyncio.to_thread(self.evidence.gather, query, document_ids)
            return context, context.model_input()

        preparation = asyncio.create_task(prepare())
        try:
            context, model_input = await asyncio.shield(preparation)
        except asyncio.CancelledError:
            # A cancelled HTTP task does not stop a filesystem thread. Retain
            # admission until that read actually finishes to bound abandoned IO.
            def release_after_read(done):
                if not done.cancelled():
                    done.exception()  # Retrieve without logging content/errors.
                    self.quota.release_before_start(reservation)
            preparation.add_done_callback(release_after_read)
            raise
        except BaseException:
            self.quota.release_before_start(reservation)
            raise
        # No refund/finish finally here: a disconnected transport does not prove
        # the independently running child stopped (or never started).
        result = await self.completion.complete(
            reservation_id=reservation, question=question,
            context=model_input, history=history)
        if self.quota.state(reservation) != 'finished':
            raise IncompleteExecution('Execution completion not verified')
        answer = await asyncio.to_thread(
            self.evidence.finalize, context, result['answer'], result['citation_ids'])
        return {**answer, 'remaining': self.quota.remaining(actor_hash)}
