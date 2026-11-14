import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { MemoryRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import api from '@/api/client'
import { fearGreedZone, lastMonths, longRangePosition, shouldAutoCollect, splitCommentary, withSearch } from '../src/lib/macroPage'
import { useAutoCollectRegimes } from '../src/hooks/useRegimes'
import type { RegimesResponse } from '../src/types'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

/* ── 자동 첫 수집 판정 (ia-redesign §4.28 결정 ①) ── */
it('auto-collects only when the history loaded empty and nothing was tried or is running', () => {
  expect(shouldAutoCollect({ loaded: true, empty: true, tried: false, pending: false })).toBe(true)
  expect(shouldAutoCollect({ loaded: false, empty: true, tried: false, pending: false })).toBe(false)   // 아직 조회 중
  expect(shouldAutoCollect({ loaded: true, empty: false, tried: false, pending: false })).toBe(false)   // 이력 있음
  expect(shouldAutoCollect({ loaded: true, empty: true, tried: true, pending: false })).toBe(false)     // 이미 한 번 시도
  expect(shouldAutoCollect({ loaded: true, empty: true, tried: false, pending: true })).toBe(false)     // 수집 중
})

const regimes = (phases: number) => ({ phases: Array.from({ length: phases }, () => ({})) }) as unknown as RegimesResponse
function Harness({ data }: { data: RegimesResponse }) {
  useAutoCollectRegimes({ isSuccess: true, isFetching: false, data })
  return null
}
const mount = (data: RegimesResponse) => render(<QueryClientProvider client={new QueryClient()}><Harness data={data} /></QueryClientProvider>)

it('posts the collect request once per page life when the history is empty, never when it exists', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { results: [], collected_at: '2026-11-05T00:00:00Z' } })
  mount(regimes(55))
  await new Promise(r => setTimeout(r, 0))
  expect(post).not.toHaveBeenCalled()
  cleanup()

  mount(regimes(0))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
  expect(post.mock.calls[0][0]).toBe('/api/spine/regimes/collect')
  cleanup()

  mount(regimes(0))   // 탭을 다시 열어도 같은 페이지 수명에서는 다시 쏘지 않는다
  await new Promise(r => setTimeout(r, 0))
  expect(post).toHaveBeenCalledTimes(1)
})

/* ── /regimes → /home/macro#history (쿼리 유지, 해시는 쿼리 뒤) ── */
it('keeps the query and puts the hash after it when redirecting', () => {
  expect(withSearch('/home/macro#history', '?regime_range=20y')).toBe('/home/macro?regime_range=20y#history')
  expect(withSearch('/home/macro', '?a=1')).toBe('/home/macro?a=1')
  expect(withSearch('/home/macro#history', '')).toBe('/home/macro#history')
})

function Where() { const l = useLocation(); return <output>{l.pathname + l.search + l.hash}</output> }
function Redirect({ to }: { to: string }) { const { search } = useLocation(); return <Navigate to={withSearch(to, search)} replace /> }
it('lands on the macro history anchor with the old query', () => {
  const { container } = render(<MemoryRouter initialEntries={['/regimes?regime_overlay=us10y']}>
    <Routes><Route path="/regimes" element={<Redirect to="/home/macro#history" />} /><Route path="/home/macro" element={<Where />} /></Routes>
  </MemoryRouter>)
  expect(container.textContent).toBe('/home/macro?regime_overlay=us10y#history')
})

/* ── AI 해설 접기 · 리스크 타일 배지 ── */
it('splits the commentary into the one-line summary and the rest', () => {
  const body = '## 한 줄 요약\n경고등은 모두 꺼져 있습니다.\n\n## 지금 하락 국면인가\n- 종가가 위에 있습니다.'
  expect(splitCommentary(body)).toEqual({ lead: '경고등은 모두 꺼져 있습니다.', rest: '## 지금 하락 국면인가\n- 종가가 위에 있습니다.' })
  expect(splitCommentary('제목 없는 한 단락')).toEqual({ lead: '제목 없는 한 단락', rest: '' })
})

const series = (from: string, n: number, f: (i: number) => number): [string, number][] =>
  Array.from({ length: n }, (_, i) => [new Date(Date.parse(from) + i * 7 * 86_400_000).toISOString().slice(0, 10), f(i)])

it('places the current value within the last 5 years and reports the real coverage', () => {
  const five = series('2021-11-05', 261, i => i)            // 5년 주간, 단조 증가
  expect(longRangePosition(five, 260, '2026-11-02')).toEqual({ position: '높음', years: 5 })
  expect(longRangePosition(five, 3, '2026-11-02')).toEqual({ position: '낮음', years: 5 })
  expect(longRangePosition(five, 130, '2026-11-02')).toEqual({ position: '보통', years: 5 })
  const short = series('2025-08-25', 62, i => i)            // 관측 1년 남짓 → '1년'으로 정직하게
  expect(longRangePosition(short, 61, '2026-11-02')?.years).toBe(1)
  expect(longRangePosition(short.slice(0, 5), 1, '2026-11-02')).toBeNull()
  expect(longRangePosition(five, null, '2026-11-02')).toBeNull()
})

it('labels fear & greed by CNN zones and trims sparklines to 6 months', () => {
  expect([10, 30, 50, 60, 90].map(fearGreedZone)).toEqual(['극단적 공포', '공포', '중립', '탐욕', '극단적 탐욕'])
  expect(lastMonths([['2026-04-01', 1], ['2026-05-03', 2], ['2026-11-02', 3]], '2026-11-02', 6).map(p => p[0])).toEqual(['2026-05-03', '2026-11-02'])
})
