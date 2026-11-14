import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import type { TimelineChannel } from '../src/types'

/* 피드 리더(D-325, 옛 ChannelReader) — '전체' 안 읽음 = 사람 소스만(D-301), '모두 읽음' = 지금 종류 칩 범위로 한 번에 */
const ch = (id: string, count: number, unread: number): TimelineChannel =>
  ({ id, name: id, platform: id.split(':')[0] as TimelineChannel['platform'], count, unread, latest_at: '2026-11-04T00:00:00Z', preview: '최근 글' })
const CHANNELS = [ch('telegram:a', 120, 3), ch('youtube:b', 30, 2), ch('memo:c', 5, 0), { ...ch('narrative:all', 900, 4), platform: 'system' as const }]
const markAll = vi.fn()
const timeline = vi.fn()

vi.mock('@/hooks/useFeed', () => ({ useFeedTotal: () => 54_021 }))
vi.mock('@/hooks/useTimeline', () => ({
  useTimeline: (f: unknown) => { timeline(f); return { isLoading: false, isError: false, isFetching: false, data: { items: [], page: 1, size: 20, has_more: false, until: '' }, refetch: () => {} } },
  useTimelineChannels: () => ({ isLoading: false, isError: false, isFetching: false, data: { items: CHANNELS, total: 1055, total_unread: 9, until: '' }, refetch: () => {} }),
  useMarkChannelRead: () => ({ mutate: vi.fn(), isPending: false }),
  useMarkAllRead: () => ({ mutate: markAll, isPending: false }),
}))
vi.mock('@/hooks/useFeedTopics', () => ({ useFeedTopics: () => ({ themes: ['AI'], stocks: ['삼성전자'] }) }))
vi.mock('@/hooks/useMarketToday', () => ({ useMarketToday: () => ({ data: { current: { label: '16:00 마감' } } }) }))
vi.mock('@/components/feed/DocumentSearch', () => ({ DocumentSearch: () => null }))
const { default: FeedPage } = await import('../src/components/feed/FeedPage')

beforeEach(() => { markAll.mockReset(); timeline.mockReset() })
afterEach(cleanup)
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}><FeedPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)
const sources = () => screen.getByRole('complementary', { name: '피드 소스 목록' })

it('restores the old reader: my feed list with type chips, source rows and the Explorer group at the bottom', () => {
  renderAt('/feed?reader_until=2026-11-04T09:00:00.000Z')
  const list = sources()
  for (const label of ['전체', '텔레그램', '블로그', '유튜브', '투자자 메모']) expect(within(within(list).getByRole('group', { name: '소스 종류' })).getByRole('button', { name: label })).toBeTruthy()
  // '전체' 줄의 안 읽음 = 사람 소스(3 + 2 + 0), Explorer 산출물(4)은 빼고 접힌 묶음으로
  expect(within(list).getByRole('button', { name: /팔로우한 소스 전체/ }).textContent).toMatch(/5$/)
  expect(within(list).getByRole('button', { name: /^Explorer/ })).toBeTruthy()
  expect(screen.getByPlaceholderText(/전체 수집 자료 54\.0천 건/)).toBeTruthy()
  // 오른쪽 위 띠 — 주제 칩과 Market Today 한 줄(세 번째 칸 없음)
  expect(screen.getByRole('button', { name: '삼성전자' })).toBeTruthy()
  const mt = screen.getByRole('link', { name: /Market Today/ }); expect([mt.textContent, mt.getAttribute('href')]).toEqual(['Market Today 16:00 정리', '/home'])
  expect(screen.queryByRole('complementary', { name: '부상 종목' })).toBeNull()
})

it('reads a picked Explorer source from the system lane even under the 전체 chip', () => {
  renderAt('/feed?channel=narrative:all&reader_until=2026-11-04T09:00:00.000Z')
  expect(timeline).toHaveBeenLastCalledWith(expect.objectContaining({ scope: 'system', source: 'all', channel: 'narrative:all' }))
  cleanup(); renderAt('/feed?channel_type=youtube&reader_until=2026-11-04T09:00:00.000Z')
  expect(timeline).toHaveBeenLastCalledWith(expect.objectContaining({ scope: 'sources', source: 'youtube' }))
})

it("marks every human source read in one call, then only the chip's platform", () => {
  renderAt('/feed?reader_until=2026-11-04T09:00:00.000Z')
  fireEvent.click(screen.getByRole('button', { name: '모두 읽음' }))
  expect(markAll).toHaveBeenCalledWith({ platform: 'all', read_until: '2026-11-04T09:00:00.000Z' }, expect.anything())
  cleanup(); renderAt('/feed?channel_type=youtube&reader_until=2026-11-04T09:00:00.000Z')
  fireEvent.click(screen.getByRole('button', { name: '모두 읽음' }))
  expect(markAll).toHaveBeenLastCalledWith({ platform: 'youtube', read_until: '2026-11-04T09:00:00.000Z' }, expect.anything())
  cleanup(); renderAt('/feed?channel_type=memo')                   // 안 읽은 글이 없으면 버튼이 없다
  expect(screen.queryByRole('button', { name: '모두 읽음' })).toBeNull()
  cleanup(); renderAt('/feed?channel=telegram:a')                  // 소스를 고르면 그 소스는 열 때 읽음 처리 — 버튼 없음
  expect(screen.queryByRole('button', { name: '모두 읽음' })).toBeNull()
})
