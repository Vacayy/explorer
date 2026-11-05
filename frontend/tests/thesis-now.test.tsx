import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import { inputsLabel, kstShort, rebuildBlockedReason, rebuildResultMessage, splitSummary, staleLevel } from '@/lib/bigPicture'
import { fireEvent } from '@testing-library/react'
import type { WorldBigPicture, WorldStrand } from '../src/types'

describe('Thesis › 지금 순수 로직 (§4.25·§4.18)', () => {
  it('낡음 규칙: 7일 넘으면 경고, 14일 넘으면 오래됨', () => {
    expect(staleLevel(null)).toBe('fresh')
    expect(staleLevel(7)).toBe('fresh')
    expect(staleLevel(8)).toBe('stale')
    expect(staleLevel(14)).toBe('stale')
    expect(staleLevel(15)).toBe('old')
  })
  it('기준 시각은 KST, 근거 범위는 0도 그대로', () => {
    expect(kstShort('2026-11-04 06:40:21')).toBe('11/4 15:40')
    expect(kstShort(null)).toBe('-')
    expect(inputsLabel({ narratives: 3, mt_sessions: 0, overnight_days: 0 })).toBe('내러티브 3편 · Market Today 0회차 · Overnight 0일')
  })
  it('3줄 요약 절을 떼어 내고 나머지는 본문으로', () => {
    const md = '## 3줄 요약\n- 하나.\n- 둘.\n1. 셋.\n\n## 본문 제목\n본문.'
    expect(splitSummary(md)).toEqual({ summary: ['하나.', '둘.', '셋.'], body: '## 본문 제목\n본문.' })
    expect(splitSummary('## 다른 제목\n본문')).toEqual({ summary: [], body: '## 다른 제목\n본문' })
  })
})

const avail = { available: true, reason: null, retry_at: null, budget_left: 7 } as const
const base: WorldBigPicture = {
  source: 'mega', strands: [], generated_at: null, week: null,
  mega: [], worldview: { briefing: '### 자리 잡은 전제\nA다.', created_at: '2026-10-25 07:02:53', stale: true }, as_of: null,
  inputs: { narratives: 18, mt_sessions: 6, overnight_days: 4 }, inputs_as_of: '2026-11-04 06:40:21',
  premises: { settled: [{ text: '주주환원이 하단을 받친다는 믿음도 굳어졌다.', shaken_by: null }],
              contested: [{ text: '공급 부족이 2027년까지 간다는 주장이 있다.', shaken_by: null }] },
  stale_days: 10, new_versions_since: 31, rebuild: avail,
}
const strand: WorldStrand = {
  title: '메모리 부족이 2위권 업체로 번지고 있습니다', status: 'strengthening',
  narratives: [{ narrative_id: 2, topic: '메모리', version: 11, created_at: '2026-11-03 02:31:18', is_new: false },
               { narrative_id: 3, topic: '정치', version: 1, created_at: '2026-11-04 06:14:38', is_new: true }],
  mt_topics: 7, mt_sessions: 4, boost: true,
  evidence: [{ kind: 'market_today', ref: 'mt:6:0', label: 'Market Today 11/4 15:40', text: '메모리 공급 부족 장기화 전망', date: '2026-11-04' },
             { kind: 'overnight', ref: 'ov:2026-11-03:3', label: 'Overnight 11/3', text: '거래대금의 81%가 반도체·소프트웨어에 몰렸고 방어주는 약했다', date: '2026-11-03' }],
}
const generated: WorldBigPicture = {
  ...base, source: 'generated', strands: [strand, { ...strand, title: '정치 변수가 새로 들어왔습니다', status: 'new', evidence: [], mt_topics: 0, boost: false }],
  generated_at: '2026-11-05 03:00:00', week: '2026-W45', stale_days: 1, new_versions_since: 0,
  premises: { settled: [{ text: '장기계약이 메모리 이익을 묶었습니다.', shaken_by: null }],
              contested: [{ text: '주주환원이 하단을 받친다는 믿음이 흔들렸습니다.',
                            shaken_by: { narrative_id: 4, topic: '주주환원', version: 8, created_at: '2026-11-03 02:35:32', is_new: false,
                                         quote: '역대급 이익에도 주가는 따라오지 못했습니다' } }] },
  rebuild: { available: false, reason: 'cooldown', retry_at: '2026-11-05 09:00:00', budget_left: 5 },
}
const state = { data: base }
const post = vi.fn()
const mutate = vi.fn()
vi.mock('@/hooks/useWorld', () => ({
  useBigPicture: () => ({ isLoading: false, isError: false, data: state.data, refetch: () => {} }),
  useBigPictureRebuild: () => ({ mutate, isPending: false }),
  useContestedPremises: () => ({ isLoading: false, isError: false, data: { items: [] } }),
  useNarrativeIndex: () => new Map(),
}))
vi.mock('@/api/client', () => ({ default: { post: (...a: unknown[]) => { post(...a); return Promise.resolve({ data: {} }) } } }))
const { BigPictureCard, PremisesCard } = await import('../src/components/world/BigPictureCard')
const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter>{ui}</MemoryRouter></TooltipProvider></QueryClientProvider>)
afterEach(() => { cleanup(); state.data = base; post.mockClear(); mutate.mockClear() })

describe('큰 그림 · 전제 칸', () => {
  it('머리에 기준 시각과 근거 범위, 7일 안 새 버전이 없으면 빈 상태', () => {
    state.data = { ...base, inputs: { narratives: 0, mt_sessions: 0, overnight_days: 0 } }
    wrap(<BigPictureCard />)
    expect(screen.getByText('기준 11/4 15:40')).toBeTruthy()
    expect(screen.getByText(/근거 내러티브 0편 · Market Today 0회차 · Overnight 0일/)).toBeTruthy()
    expect(screen.getByText('이번 주엔 새로 바뀐 서사가 없어요.')).toBeTruthy()
  })
  it('10일 지난 브리핑은 경고 띠 + 다시 만들기, 열기만으로는 생성하지 않는다', () => {
    wrap(<PremisesCard />)
    expect(screen.getByText(/10\/25에 만든 뒤 10일 지났어요\. 그 사이 새 내러티브 버전 31편이 쌓였어요\./)).toBeTruthy()
    expect(screen.getByRole('button', { name: '다시 만들기' })).toBeTruthy()
    expect(screen.getByText('주주환원이 하단을 받친다는 믿음도 굳어졌다.')).toBeTruthy()
    expect(screen.getByText('공급 부족이 2027년까지 간다는 주장이 있다.')).toBeTruthy()
    expect(post).not.toHaveBeenCalled()
  })
  it('15일 넘으면 오래됨 표시', () => {
    state.data = { ...base, stale_days: 15 }
    wrap(<PremisesCard />)
    expect(screen.getAllByText('오래됨').length).toBe(2)
  })
  it('첫 생성 전에도 다시 만들기는 큰 그림 생성(POST는 누를 때만)', () => {
    wrap(<PremisesCard />)
    expect(mutate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '다시 만들기' }))
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(post).not.toHaveBeenCalled()
  })
})

describe('주간 생성 줄기 (§4.25)', () => {
  it('줄기 격자 — 상태 배지·서사 칩(새)·Market Today 연결 수·앞당김·근거 줄', () => {
    state.data = generated
    const { container } = wrap(<BigPictureCard />)
    expect(container.querySelectorAll('[data-strand]').length).toBe(2)
    expect(screen.getByText('메모리 부족이 2위권 업체로 번지고 있습니다')).toBeTruthy()
    expect(screen.getByText('강해짐')).toBeTruthy()
    expect(screen.getByText('새로')).toBeTruthy()
    expect(screen.getByText('Market Today 화두 7 · 4회차')).toBeTruthy()
    expect(screen.getByText('다음 갱신 앞당김')).toBeTruthy()
    expect(screen.getByText('Market Today 11/4 15:40')).toBeTruthy()
    expect(screen.getByText('거래대금의 81%가 반도체·소프트웨어에 몰렸고 방어주는 약했다')).toBeTruthy()
    expect(screen.getAllByText('새').length).toBe(2)
    expect(container.querySelectorAll('[data-strand-mt]').length).toBe(1)   // 연결 0인 줄기는 줄 없음
    expect(container.querySelector('[data-stale-band]')).toBeNull()
  })
  it('쿨다운이면 다시 만들기 비활성 + 이유 툴팁, 누를 수 없다', () => {
    state.data = generated
    const { container } = wrap(<BigPictureCard />)
    const btn = screen.getByRole('button', { name: '다시 만들기' }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(container.querySelector('[data-rebuild-blocked="cooldown"]')).toBeTruthy()
    fireEvent.click(btn)
    expect(mutate).not.toHaveBeenCalled()
  })
  it('7일 넘으면 경고 띠(경과일·새 버전·다시 만들기), 14일 넘으면 흐리게 + 오래됨', () => {
    state.data = { ...generated, stale_days: 9, new_versions_since: 5, rebuild: avail }
    const { container, unmount } = wrap(<BigPictureCard />)
    expect(screen.getByText('9일 지났어요 · 그 사이 새 버전 5편')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '다시 만들기' }))
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(container.querySelector('[data-strand][data-stale]')).toBeNull()
    unmount()
    state.data = { ...generated, stale_days: 15, rebuild: avail }
    const r = wrap(<BigPictureCard />)
    expect(r.container.querySelectorAll('[data-strand][data-stale]').length).toBe(2)
    expect(screen.getAllByText('오래됨').length).toBe(2)
  })
  it('전제 칸 — 이번 주 흔들림 배지와 출처 서사 한 줄, 생성분엔 브리핑 전문·경고 띠 없음', () => {
    state.data = generated
    const { container } = wrap(<PremisesCard />)
    expect(screen.getByText('이번 주 흔들림')).toBeTruthy()
    expect(screen.getByText('주주환원 v8(11/3)')).toBeTruthy()
    expect(screen.getByText(/역대급 이익에도 주가는 따라오지 못했습니다/)).toBeTruthy()
    expect(screen.queryByText('브리핑 전문')).toBeNull()
    expect(container.querySelector('[data-stale-band]')).toBeNull()
  })
  it('다시 만들기 이유·결과 문장', () => {
    expect(rebuildBlockedReason(avail)).toBeNull()
    expect(rebuildBlockedReason({ available: false, reason: 'cooldown', retry_at: '2026-11-05 09:00:00', budget_left: 5 })).toBe('11/5 18:00 이후 다시 만들 수 있어요 (6시간 간격)')
    expect(rebuildBlockedReason({ available: false, reason: 'budget', retry_at: '2026-11-08 15:00:00', budget_left: 0 })).toBe('이번 주 생성 7회를 다 썼어요 · 11/9부터 다시')
    expect(rebuildResultMessage({ status: 'skipped' }).ok).toBe(true)
    expect(rebuildResultMessage({ status: 'budget' }).text).toBe('이번 주 생성 7회를 다 썼습니다')
    expect(rebuildResultMessage({ status: 'cooldown', retry_at: '2026-11-05 09:00:00' })).toEqual({ ok: false, text: '11/5 18:00 이후 다시 만들 수 있습니다' })
    expect(rebuildResultMessage({ status: 'failed' }).text).toContain('이전 것을 그대로')
  })
})
