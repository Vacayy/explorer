import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import { inputsLabel, kstShort, splitSummary, staleLevel } from '@/lib/bigPicture'
import type { WorldBigPicture } from '../src/types'

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

const base: WorldBigPicture = {
  mega: [], worldview: { briefing: '### 자리 잡은 전제\nA다.', created_at: '2026-10-25 07:02:53', stale: true }, as_of: null,
  inputs: { narratives: 18, mt_sessions: 6, overnight_days: 4 }, inputs_as_of: '2026-11-04 06:40:21',
  premises: { settled: ['주주환원이 하단을 받친다는 믿음도 굳어졌다.'], contested: ['공급 부족이 2027년까지 간다는 주장이 있다.'] },
  stale_days: 10, new_versions_since: 31,
}
const state = { data: base }
const post = vi.fn()
vi.mock('@/hooks/useWorld', () => ({
  useBigPicture: () => ({ isLoading: false, isError: false, data: state.data, refetch: () => {} }),
  useContestedPremises: () => ({ isLoading: false, isError: false, data: { items: [] } }),
  useNarrativeIndex: () => new Map(),
}))
vi.mock('@/api/client', () => ({ default: { post: (...a: unknown[]) => { post(...a); return Promise.resolve({ data: {} }) } } }))
const { BigPictureCard, PremisesCard } = await import('../src/components/world/BigPictureCard')
const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter>{ui}</MemoryRouter></TooltipProvider></QueryClientProvider>)
afterEach(() => { cleanup(); state.data = base; post.mockClear() })

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
})
