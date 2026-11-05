import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'

// 관리자(ia-redesign §4.31) — 훅을 바꿔 끼워 화면 규칙만 본다. 플래그 변경(POST)은 부르지 않는다
const ok = <T,>(data: T) => ({ data, isPending: false, isError: false, isFetching: false, isPlaceholderData: false, refetch: vi.fn() })
const failed = { data: undefined, isPending: false, isError: true, isFetching: false, isPlaceholderData: false, refetch: vi.fn() }
const mutate = vi.fn()
const state: Record<string, unknown> = {}
vi.mock('@/hooks/useAdmin', () => ({
  useAdminJobs: () => state.jobs,
  useAdminRuns: () => state.runs,
  useAdminHealth: () => state.health,
  useCurationLog: (kind: string | null, verdict: string | null) => (state.curation as (k: string | null, v: string | null) => unknown)(kind, verdict),
  useSetFlag: () => ({ mutate, isPending: false }),
}))
vi.mock('@/hooks/useRegimes', () => ({ useCollectRegimes: () => ({ mutate: vi.fn(), isPending: false }) }))
vi.mock('@/components/admin/ObservePanel', () => ({ ObservePanel: () => <p>관측 본문</p> }))
vi.mock('@/components/admin/SourcesPanel', () => ({ SourcesPanel: () => <p>소스 본문</p> }))
const { default: AdminPage } = await import('../src/components/admin/AdminPage')

afterEach(() => { cleanup(); mutate.mockReset() })

const LOG = {
  apply_enabled: false,
  counts: { vocab_merge: { hold: 6 }, knowledge: { hold: 30, approve: 2 } },
  items: [
    { kind: 'vocab_merge', target_id: 7, title: "'레조' → '레조낙' 통합?", verdict: 'hold', rule: '회사 약칭 — 다른 회사일 수 있음', applied: false, decided_at: '2026-11-04 11:39:52' },
    { kind: 'vocab_merge', target_id: 8, title: '#8', verdict: 'approve', rule: null, applied: true, decided_at: '2026-11-04 11:39:52' },
  ],
}

function Where() { const l = useLocation(); return <output data-testid="where">{l.pathname + l.search}</output> }
function renderAt(path: string) {
  return render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/admin" element={<><AdminPage /><Where /></>} /><Route path="/admin/sources" element={<><AdminPage /><Where /></>} /></Routes>
  </MemoryRouter></TooltipProvider></QueryClientProvider>)
}

it('shows four views and sends the old ?view=sources to /admin/sources', () => {
  state.curation = () => ok(LOG)
  renderAt('/admin?view=sources')
  expect(screen.getByTestId('where').textContent).toBe('/admin/sources')
  expect(screen.getByText('소스 본문')).toBeTruthy()
  for (const v of ['작업·신선도', '관측', '소스', '자동 정리']) expect(screen.getByRole('radio', { name: v })).toBeTruthy()
})

it('curation: counts table with a planned person row, KST times, and applied merges marked as undoable', () => {
  state.curation = () => ok(LOG)
  renderAt('/admin?view=curation')
  expect(screen.getByText('판정만 기록 중')).toBeTruthy()
  expect(screen.getByText('예정')).toBeTruthy()
  expect(screen.getByText('모두 38건')).toBeTruthy()
  // UTC 11:39 → KST 20:39
  expect(screen.getAllByText('11-04 20:39').length).toBe(2)
  expect(screen.getByText('되돌리기 재료 있음')).toBeTruthy()
  expect(screen.getByText('#8')).toBeTruthy()
  // 기록 보기 — 누르는 것은 적용 스위치 하나
  expect(screen.getAllByRole('switch').length).toBe(1)
  expect(mutate).not.toHaveBeenCalled()
})

it('curation: filters come from the URL and an empty result says so', () => {
  state.curation = (kind: string | null, verdict: string | null) => kind === 'alias' && verdict === 'reject' ? ok({ ...LOG, items: [] }) : ok(LOG)
  renderAt('/admin?view=curation&kind=alias&verdict=reject')
  expect(screen.getByText('이 조건의 판정이 없습니다')).toBeTruthy()
  expect(screen.getByRole('radio', { name: '거부 0' }).getAttribute('aria-checked')).toBe('true')
})

it('curation: no records at all → empty line; failure → retry', () => {
  state.curation = () => ok({ apply_enabled: false, counts: {}, items: [] })
  renderAt('/admin?view=curation')
  expect(screen.getByText('아직 판정한 정리 작업이 없습니다')).toBeTruthy()
  cleanup()
  state.curation = () => failed
  renderAt('/admin?view=curation')
  expect(screen.getByRole('alert').textContent).toContain('다시 시도')
})

it('ops: a failed freshness block does not hide jobs or runs; run times are KST', () => {
  state.health = failed
  state.jobs = ok([
    { name: 'auto_curation', label: '정리 작업 자동 처리', description: 'd', entrypoint: 'e', enabled: true, last_run: null },
    { name: 'scan_actions', label: '기업활동 스캔', description: 'd', entrypoint: 'e', enabled: false, last_run: { status: 'error', summary: 'boom', duration_ms: 2940, ran_at: '2026-11-04 13:58:54' } },
  ])
  state.runs = ok([{ job: 'scan_actions', status: 'error', summary: 'boom', duration_ms: 2940, ran_at: '2026-11-04 13:58:54' }])
  state.curation = () => ok(LOG)
  renderAt('/admin')
  expect(screen.getByText('신선도 점검을 불러오지 못했습니다.')).toBeTruthy()
  expect(screen.getByText('기업활동 스캔')).toBeTruthy()
  expect(screen.getByText('다음 주간 제안 스캔(일 07:20)에서 처음 돕니다')).toBeTruthy()
  expect(screen.getByText('새로')).toBeTruthy()
  expect(screen.getByText('1/2 켜짐')).toBeTruthy()
  expect(screen.getByText('오류 1')).toBeTruthy()
  expect(screen.getAllByText('11-04 22:58').length).toBeGreaterThan(0)
  expect(screen.getAllByText('실패').length).toBe(2)
})
