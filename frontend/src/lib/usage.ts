import { matchPath } from 'react-router-dom'
import { API_BASE } from '@/api/client'
import { analyzeTabOf, locate } from '@/components/layout/navConfig'

/** 사용 이벤트 (docs/specs/observability.md §사용 이벤트, D-283).
 * 화면 진입(view)·이탈(leave, 보이는 동안 머문 시간)·핵심 동작(action)·생성물 열람(open)을 묶어 10초마다 보낸다.
 * 화면 이름은 라우트 패턴(실제 값 아님), 무엇을 봤는지는 entity로. 개인 투자 내용(금액·수량·메모 본문)은 넣지 않는다.
 * 각 이벤트에 IA 위치(section·tab, navConfig.locate)를 붙여 대메뉴·탭 단위로 모은다.
 * 보내기 실패는 무시한다(화면에 영향 없음). 테스트 환경(vitest)·자동화 브라우저(webdriver·headless)는 보내지 않는다. */
export type UsageType = 'view' | 'leave' | 'action' | 'open'
interface UsageEvent {
  ts: string; session: string; type: UsageType; name: string; ref?: string; entity?: string; dwell_ms?: number
  section?: string; tab?: string
}

const ENDPOINT = `${API_BASE}/api/spine/usage`
const IDLE_MS = 30 * 60_000
/** 자동화 브라우저로 화면을 점검할 때만 켜는 수동 기록 스위치 — localStorage['explorer.usage.force']='1' */
export const FORCE_KEY = 'explorer.usage.force'
const queue: UsageEvent[] = []

/** 사람이 아닌 브라우저(Playwright·Puppeteer·headless Chrome) — 점검 스크립트가 사용 기록을 부풀리지 않게 */
export function isAutomated(nav: Pick<Navigator, 'webdriver' | 'userAgent'> | undefined = typeof navigator === 'undefined' ? undefined : navigator,
  store: Pick<Storage, 'getItem'> | undefined = typeof localStorage === 'undefined' ? undefined : localStorage): boolean {
  try { if (store?.getItem(FORCE_KEY) === '1') return false } catch { /* 저장소 막힘 */ }
  return !!nav && (nav.webdriver === true || /HeadlessChrome/i.test(nav.userAgent ?? ''))
}

const enabled = () => typeof window !== 'undefined' && import.meta.env?.MODE !== 'test' && !isAutomated()

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

/** IA 위치 — 대메뉴(L1)·탭(L2). L1 밖은 도시에·대화·관리자로 묶고, 나머지는 비운다 */
export function placeOf(pathname: string, search = ''): { section?: string; tab?: string } {
  const at = locate(pathname, search)
  if (at) return at
  if (pathname.startsWith('/analyze/')) return { section: 'dossier', tab: analyzeTabOf(pathname) ?? undefined }
  if (/^\/us\/[^/]+/.test(pathname)) return { section: 'dossier', tab: 'us' }
  if (pathname === '/chat' || pathname === '/ask') return { section: 'chat' }
  if (pathname.startsWith('/admin')) return { section: 'admin', tab: pathname === '/admin/sources' ? 'sources' : new URLSearchParams(search).get('view') ?? 'ops' }
  return {}
}

type TrackOpts = { ref?: string; entity?: string | number | null; dwell_ms?: number; section?: string; tab?: string }

/** section·tab을 주지 않으면 지금 주소에서 판정한다(동작·열람). view·leave는 화면 기준 값을 넘긴다 */
export function track(type: UsageType, name: string, opts: TrackOpts = {}) {
  if (!enabled() || !name) return
  const place = opts.section !== undefined || opts.tab !== undefined ? { section: opts.section, tab: opts.tab } : placeOf(location.pathname, location.search)
  queue.push({ ts: new Date().toISOString(), session: session(), type, name, ref: opts.ref,
    entity: opts.entity == null ? undefined : String(opts.entity), dwell_ms: opts.dwell_ms, section: place.section, tab: place.tab })
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
  '/industry/:sector', '/follow/trade/:hs', '/follow/taiwan/:code', '/person/:id',
]
/** 화면을 가르는 쿼리 — 값까지 이름에 넣는다 */
const NAMED_QUERY = ['view', 'tab', 'home_view']
/** 상세를 여는 쿼리 — 있는지 없는지는 화면 이름에(`?t`), 값은 entity. 같은 화면에서 값만 바뀌면 열람(open) */
const DETAIL_QUERY: Record<string, string> = { t: 'transcript.open', topic: 'narrative.open' }
/** 화면 안 상태 쿼리 — 이름에 넣지 않고 entity로. 값이 바뀌면 새 방문이 아니라 동작·열람 하나 */
const STATE_QUERY: Record<string, { type: 'action' | 'open'; name: string }> = {
  group: { type: 'action', name: 'peer.group' },
  stock: { type: 'action', name: 'peer.stock' },
  sector: { type: 'action', name: 'season.sector' },
  hs: { type: 'open', name: 'monitor.open' },   // 수출입 품목 대화상자
  tw: { type: 'open', name: 'monitor.open' },   // 대만 회사 대화상자
}

export interface Screen {
  name: string
  entity?: string
  /** 경로 값(종목코드·섹터 등) — 다르면 다른 화면 */
  path?: string
  /** 상세·상태 쿼리 값 */
  keys: Record<string, string>
}

/** 브라우저 주소의 경로 값은 퍼센트 인코딩돼 온다(`/industry/%EB%B0%98…`) — 사람이 읽는 값으로 */
const decode = (v: string) => { try { return decodeURIComponent(v) } catch { return v } }

export function screenOf(pathname: string, search: string): Screen {
  let name = pathname.replace(/\/+$/, '') || '/'
  let path: string | undefined
  for (const p of PATTERNS) {
    const m = matchPath(p, name)
    if (m) {
      path = Object.entries(m.params).filter(([k]) => k !== 'tab').map(([, v]) => decode(v ?? '')).join('/') || undefined
      name = p.replace(':tab', m.params.tab ?? ':tab')
      break
    }
  }
  const q = new URLSearchParams(search)
  const named = NAMED_QUERY.filter(k => q.get(k)).map(k => `${k}=${q.get(k)}`)
  const detail = Object.keys(DETAIL_QUERY).filter(k => q.get(k))
  if (named.length || detail.length) name += '?' + [...named, ...detail].join('&')
  const keys: Record<string, string> = {}
  for (const k of [...detail, ...Object.keys(STATE_QUERY)]) { const v = q.get(k); if (v) keys[k] = v }
  const entity = [path, ...Object.values(keys)].filter(Boolean).join('/') || undefined
  return { name, entity, path, keys }
}

/** 같은 화면 안에서 바뀐 것 → 동작·열람 이벤트. 다른 화면이면 null(새 view·leave) */
export function inPageEvents(prev: Screen, next: Screen): { type: 'action' | 'open'; name: string; entity: string }[] | null {
  if (prev.name !== next.name || prev.path !== next.path) return null
  const out: { type: 'action' | 'open'; name: string; entity: string }[] = []
  for (const [k, v] of Object.entries(next.keys)) {
    if (prev.keys[k] === v) continue
    const ev = DETAIL_QUERY[k] ? { type: 'open' as const, name: DETAIL_QUERY[k] } : STATE_QUERY[k]
    if (ev) out.push({ ...ev, entity: v })
  }
  return out
}

if (enabled()) {
  setInterval(flushUsage, 10_000)
  window.addEventListener('pagehide', flushUsage)
}
