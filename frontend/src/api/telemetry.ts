import type { ApiError } from './errors.ts'

/** 응답 래퍼 오류 기록 (docs/specs/frontend-api-reliability.md §오류 기록).
 * 계약 위반·5xx·timeout·네트워크를 콘솔과 서버(/api/spine/client-errors)에 남긴다. 4xx는 입력·없는 자원이라 제외.
 * 같은 API·필드·종류는 10분에 한 번만 — 화면이 여러 번 재시도해도 서버 기록이 폭주하지 않게. 보고 실패는 무시한다. */
const WINDOW_MS = 600_000

/** 테스트(vitest MODE=test)에서는 서버로 보내지 않는다 — 테스트가 일부러 낸 오류가 운영 기록에 섞였다(2026-10-31).
 * 보고 자체를 검사하는 테스트만 globalThis.__API_TELEMETRY_TEST__ = true로 켠다. */
function sendEnabled() {
  return import.meta.env?.MODE !== 'test' || (globalThis as { __API_TELEMETRY_TEST__?: boolean }).__API_TELEMETRY_TEST__ === true
}
const seen = new Map<string, number>()

export function issueField(err: ApiError) {
  const issue = err.issues?.[0]
  return issue ? issue.path.map(String).join('.') : ''
}

export function reportApiError(err: ApiError, base: string) {
  if (!err.endpoint || (err.kind === 'http' && (err.status ?? 0) < 500)) return
  const field = issueField(err)
  const sig = `${err.endpoint}|${err.kind}|${err.status ?? ''}|${field}`
  const now = Date.now()
  if ((seen.get(sig) ?? 0) > now - WINDOW_MS) return
  seen.set(sig, now)
  const detail = err.issues?.[0]?.message ?? err.message
  console.warn('[api]', err.kind, err.endpoint, err.status ?? '', field, detail, err.issues ?? '')
  if (typeof fetch !== 'function' || err.endpoint.includes('/client-errors') || !sendEnabled()) return
  void fetch(`${base}/api/spine/client-errors`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, keepalive: true,
    body: JSON.stringify({
      endpoint: err.endpoint, kind: err.kind, status: err.status ?? null, field, detail: detail.slice(0, 500),
      issues: (err.issues ?? []).slice(0, 5).map(i => ({ path: i.path.map(String), message: i.message })),
      page: typeof location === 'undefined' ? '' : (location.pathname + location.search).slice(0, 300),
    }),
  }).catch(() => {})
}
