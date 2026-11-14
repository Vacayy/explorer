import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { chipLine, chipTip, mdDate } from '@/lib/narrativeLinks'
import type { NarrativeCandidate, NarrativeMarketToday, TopicNarrative } from '../src/types'

const nar = (topic: string, rule: number, doc_overlap: number): TopicNarrative =>
  ({ topic, narrative_id: 1, version: 34, created_at: '2026-10-28 06:54:50', rule, doc_overlap })

describe('화두 → 내러티브 순수 로직 (§9)', () => {
  it('칩은 두 개까지, 나머지는 +N', () => {
    const { shown, rest } = chipLine([nar('AI', 2, 2), nar('반도체', 3, 2), nar('지정학', 3, 2)])
    expect(shown.map(n => n.topic)).toEqual(['AI', '반도체'])
    expect(rest.map(n => n.topic)).toEqual(['지정학'])
  })
  it('툴팁은 규칙·겹친 출처·버전·KST 갱신일', () => {
    expect(chipTip(nar('AI', 1, 1))).toEqual(['태그 일치 · 출처 1건 겹침', '서사 v34 · 10/28 갱신'])
    expect(mdDate('2026-11-03')).toBe('11/3')
  })
})

const timeline: NarrativeMarketToday = {
  topic: '메모리', narrative_id: 445, collected_since: '2026-11-03',
  days: [{ trade_date: '2026-11-05', cells: [
    { slot: '0930', label: '09:30', state: 'linked', wrap: false }, { slot: '1130', label: '11:30', state: 'unlinked', wrap: false },
    { slot: '1500', label: '15:00', state: 'scheduled', wrap: false }, { slot: '1600', label: '16:00 마감', state: 'scheduled', wrap: true }] }],
  items: [{ mt_id: 3, trade_date: '2026-11-03', slot: '1540', label: '15:40', title: '메모리 공급 부족 장기화 전망', rule: 1, doc_overlap: 1, wrap: false }],
  week_topics: 2, week_sessions: 2, boost: true,
}
const cand = (over: Partial<NarrativeCandidate>): NarrativeCandidate => ({
  tag: '중간선거', name: '중간선거', status: 'pending', first_seen: '2026-11-03', last_seen: '2026-11-04', days: 2, sessions: 3, sources: 8,
  tags: ['중간선거'], session_list: [{ mt_id: 3, trade_date: '2026-11-03', slot: '1540', label: '15:40' }],
  titles: ['미국 중간선거 앞둔 경계감'], linked: ['지정학', '변동성'], merge_into: null, narrative_topic: null, attempt: null, ...over,
})
const state: { tl: { data?: NarrativeMarketToday; isError: boolean }; cands: { data?: { items: NarrativeCandidate[] }; isLoading: boolean; isError: boolean } } = {
  tl: { data: timeline, isError: false }, cands: { data: { items: [] }, isLoading: false, isError: false },
}
const mutate = vi.fn()
vi.mock('@/hooks/useNarrativeLinks', () => ({
  useNarrativeTimeline: () => state.tl,
  useNarrativeCandidates: () => ({ ...state.cands, refetch: () => {} }),
  useCandidateAction: () => ({ mutate, isPending: false }),
}))
const { NarrativeChipLine } = await import('../src/components/world/NarrativeChipLine')
const { MarketTodayTimeline } = await import('../src/components/world/MarketTodayTimeline')
const { NarrativeCandidatesCard } = await import('../src/components/world/NarrativeCandidatesCard')
const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
afterEach(() => {
  cleanup(); mutate.mockClear()
  state.tl = { data: timeline, isError: false }
  state.cands = { data: { items: [] }, isLoading: false, isError: false }
})

describe('칩 줄', () => {
  it('연결이 없으면 줄 자체가 없다', () => {
    const { container } = wrap(<NarrativeChipLine items={[]} />)
    expect(container.querySelector('[data-narrative-chips]')).toBeNull()
  })
  it('칩 두 개는 내러티브 상세로, 나머지는 +N', () => {
    wrap(<NarrativeChipLine items={[nar('AI', 2, 2), nar('반도체', 3, 2), nar('지정학', 3, 2)]} />)
    expect(screen.getByRole('link', { name: 'AI ›' }).getAttribute('href')).toBe('/narrative?topic=AI')
    expect(screen.getByRole('link', { name: '반도체 ›' })).toBeTruthy()
    expect(screen.getByText('+1')).toBeTruthy()
    expect(screen.queryByRole('link', { name: '지정학 ›' })).toBeNull()
  })
})

describe('장중 화두 타임라인', () => {
  it('격자 칸 상태·연결 화두·집계 한 줄', () => {
    const { container } = wrap(<MarketTodayTimeline narrativeId={445} />)
    expect([...container.querySelectorAll('[role=cell]')].map(c => c.getAttribute('data-state'))).toEqual(['linked', 'unlinked', 'scheduled', 'scheduled'])
    expect(screen.getByLabelText('11/5 16:00 마감 예정')).toBeTruthy()
    expect(screen.getByText('메모리 공급 부족 장기화 전망')).toBeTruthy()
    expect(screen.getByText('태그 일치 · 출처 1건 겹침')).toBeTruthy()
    expect(screen.getByText('11/3부터 수집')).toBeTruthy()
    expect(screen.getByText('다음 갱신 앞당김')).toBeTruthy()
  })
  it('연결이 없으면 한 줄, 오류면 통째로 숨김', () => {
    state.tl = { data: { ...timeline, items: [], boost: false }, isError: false }
    wrap(<MarketTodayTimeline narrativeId={445} />)
    expect(screen.getByText('이번 주 Market Today에서 이 서사가 나오지 않았어요.')).toBeTruthy()
    cleanup()
    state.tl = { data: undefined, isError: true }
    const { container } = wrap(<MarketTodayTimeline narrativeId={445} />)
    expect(container.querySelector('[data-mt-timeline]')).toBeNull()
  })
})

describe('내러티브 후보 카드', () => {
  it('비면 빈 문구', () => {
    wrap(<NarrativeCandidatesCard />)
    expect(screen.getByText('반복되는 새 화두가 없어요.')).toBeTruthy()
  })
  it('후보는 만들기·무시, 관찰 중은 버튼 없음, 열기만으로 POST 없음', () => {
    state.cands = { ...state.cands, data: { items: [cand({}), cand({ tag: '이란', name: '이란 · 케슘섬', status: 'watching', days: 1 })] } }
    wrap(<NarrativeCandidatesCard />)
    expect(screen.getByText('2일 · 3회차 · 출처 8건')).toBeTruthy()
    expect(screen.getByText('관찰 중')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: '서사로 만들기' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: '무시' })).toHaveLength(1)
    expect(mutate).not.toHaveBeenCalled()
    screen.getByRole('button', { name: '무시' }).click()
    expect(mutate).toHaveBeenCalledWith({ tag: '중간선거', action: 'dismiss' }, expect.anything())
  })
  it('같은 기간 새 서사와 출처가 겹치면 합치기 버튼', () => {
    state.cands = { ...state.cands, data: { items: [cand({ merge_into: { topic: '정치', overlap: 2, narrative_id: 9, version: 1, created_at: null } })] } }
    wrap(<NarrativeCandidatesCard />)
    expect(screen.getByRole('button', { name: "'정치'에 합치기" })).toBeTruthy()
  })
})
