"""Bounded local dispatcher transport; no retries, logs, or quota transitions."""
import asyncio
import json
import math
from pathlib import Path
import re

REQUEST_BYTES = 160 * 1024
RESPONSE_BYTES = 128 * 1024
_HEX = re.compile(r'[0-9a-f]{64}', re.ASCII)


class CompletionUnavailable(Exception):
    """Fixed transport failure without request, credential, or provider text."""


class CompletionNotSubmitted(CompletionUnavailable):
    """Transport failed before any request bytes could be submitted."""


class CompletionCancelledBeforeSend(asyncio.CancelledError):
    """Cancellation before submission; the dispatcher cannot have this request."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class PublicCompletionClient:
    def __init__(self, socket_path: Path, token: str, timeout=190):
        path = Path(socket_path)
        if not path.is_absolute():
            raise ValueError('Absolute dispatcher socket path required')
        if not isinstance(token, str) or _HEX.fullmatch(token) is None:
            raise ValueError('Invalid dispatcher credential')
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError('Invalid dispatcher timeout')
        self._path = path
        self._token = token
        self._timeout = timeout

    async def complete(self, reservation_id, question, context, history):
        writer = None
        sent_or_uncertain = False
        try:
            if not isinstance(reservation_id, str) or _HEX.fullmatch(reservation_id) is None:
                raise ValueError
            if not isinstance(question, str) or not isinstance(context, str):
                raise ValueError
            if not isinstance(history, (tuple, list)):
                raise ValueError
            request = {'version': 1, 'token': self._token, 'operation': 'complete',
                       'reservation_id': reservation_id, 'question': question,
                       'context': context, 'history': history}
            # Incremental encoding prevents constructing an unbounded aggregate.
            encoded = bytearray()
            encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            for chunk in encoder.iterencode(request):
                chunk = chunk.encode('utf8')
                if len(encoded) + len(chunk) + 1 > REQUEST_BYTES:
                    raise ValueError
                encoded.extend(chunk)
            encoded.extend(b'\n')
            async with asyncio.timeout(self._timeout):
                reader, writer = await asyncio.open_unix_connection(str(self._path), limit=RESPONSE_BYTES)
                # write() can partially submit before raising. From this point,
                # only dispatcher reconciliation can prove execution status.
                sent_or_uncertain = True
                writer.write(encoded)
                await writer.drain()
                line = await reader.readuntil(b'\n')
                if len(line) > RESPONSE_BYTES:
                    raise ValueError
                response = json.loads(line.decode('utf8'), object_pairs_hook=_unique_object)
                if not isinstance(response, dict) or set(response) != {
                        'version', 'status', 'reservation_id', 'answer', 'citation_ids'}:
                    raise ValueError
                if (type(response['version']) is not int or response['version'] != 1
                        or response['status'] != 'complete' or response['reservation_id'] != reservation_id):
                    raise ValueError
                answer, citations = response['answer'], response['citation_ids']
                if not isinstance(answer, str) or not answer.strip() or len(answer.encode('utf8')) > 16 * 1024:
                    raise ValueError
                if (not isinstance(citations, list) or not 1 <= len(citations) <= 4
                        or any(not isinstance(item, str) or item not in ('D1', 'D2', 'D3', 'D4')
                               for item in citations)
                        or len(set(citations)) != len(citations)):
                    raise ValueError
                return {'answer': answer, 'citation_ids': citations}
        except asyncio.CancelledError:
            if not sent_or_uncertain:
                raise CompletionCancelledBeforeSend() from None
            raise
        except (OSError, TimeoutError, ValueError, TypeError, RecursionError,
                asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            failure = CompletionUnavailable if sent_or_uncertain else CompletionNotSubmitted
            raise failure('Public completion unavailable') from None
        finally:
            if writer is not None:
                writer.close()
                # Cancellation during drain must not leave queued writes alive.
                writer.transport.abort()
