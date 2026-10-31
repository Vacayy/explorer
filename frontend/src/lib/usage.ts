import { matchPath } from 'react-router-dom'
import { API_BASE } from '@/api/client'

/** 사용 이벤트 (docs/specs/observability.md §사용 이벤트, D-283).
 * 화면 진입(view)·이탈(leave, 보이는 동안 머문 시간)·핵심 동작(action)·생성물 열람(open)을 묶어 10초마다 보낸다.
 * 화면 이름은 라우트 패턴(실제 값 아님), 무엇을 봤는지는 entity로. 개인 투자 내용(금액·수량·메모 본문)은 넣지 않는다.
 * 보내기 실패는 무시한다(화면에 영향 없음). 테스트 환경(vitest)은 보내지 않는다. */
export type UsageType = 'view' | 'leave' | 'action' | 'open'
interface UsageEvent { ts: string; session: string; type: UsageType; name: string; ref?: string; entity?: string; dwell_ms?: number }

const ENDPOINT = `${API_BASE}/api/spine/usage`
const IDLE_MS = 30 * 60_000
const queue: UsageEvent[] = []
const enabled = () => typeof window !== 'undefined' && import.meta.env?.MODE !== 'test'

function session(): string {
  try {
    const now = Date.now()
    const raw = sessionStorage.getItem('usage.session')
    const [id, last] = raw ? raw.split('|') : []
    const sid = id && now - Number(last) < IDLE_MS ? id : Math.random().toString(36).slice(2, 10)
    sessionStorage.setItem('usage.session', `${sid}|${now}`)
    return sid
  } catch {
    return 'nostore'
  }
}

export function track(type: UsageType, name: string, opts: { ref?: string; entity?: string | number | null; dwell_ms?: number } = {}) {
  if (!enabled() || !name) return
  queue.push({ ts: new Date().toISOString(), session: session(), type, name, ref: opts.ref,
    entity: opts.entity == null ? undefined : String(opts.entity), dwell_ms: opts.dwell_ms })
  if (queue.length >= 50) flushUsage()
}

export function flushUsage() {
  if (!queue.length) return
  const events = queue.splice(0, queue.length)
  // keepalive: 탭을 닫는 순간에도 전송이 끝까지 간다(sendBeacon은 교차 출처 JSON을 못 보낸다)
  void fetch(ENDPOINT, { method: 'POST', headers: { 'content-type': 'application/json' }, keepalive: true, body: JSON.stringify({ events }) })
    .catch(() => {})
}

/** 값이 들어가는 경로 — 패턴으로 바꾼다(App.tsx 라우트). 위에서부터 먼저 맞는 것 */
const PATTERNS = [
  '/analyze/compare', '/analyze/:stockCode/:tab', '/analyze/:stockCode', '/us/:ticker', '/doc/:docId', '/synthesis/:synthesisId',
  '/question/:id', '/study/projects/:id', '/study/:id', '/home/b/:boardId', '/company/:stockCode/:tab',
]
/** 화면을 가르는 쿼리 — 값까지 이름에 넣는 것(view·tab)과 '무엇을 봤나'(entity)로 보내는 것 */
const NAMED_QUERY = ['view', 'tab']
const ENTITY_QUERY = ['t', 'sector', 'stock', 'topic', 'group']

export function screenOf(pathname: string, search: string): { name: string; entity?: string } {
  let name = pathname.replace(/\/+$/, '') || '/'
  let entity: string | undefined
  for (const p of PATTERNS) {
    const m = matchPath(p, name)
    if (m) {
      const params = Object.entries(m.params).filter(([k]) => k !== 'tab')
      entity = params.map(([, v]) => v).join('/') || undefined
      name = p.replace(':tab', m.params.tab ?? ':tab')
      break
    }
  }
  const q = new URLSearchParams(search)
  const named = NAMED_QUERY.filter(k => q.get(k)).map(k => `${k}=${q.get(k)}`)
  const marked = ENTITY_QUERY.filter(k => q.get(k))
  if (named.length || marked.length) name += '?' + [...named, ...marked].join('&')
  entity ??= marked.map(k => q.get(k)).join('/') || undefined
  return { name, entity }
}

if (enabled()) {
  setInterval(flushUsage, 10_000)
  window.addEventListener('pagehide', flushUsage)
}
