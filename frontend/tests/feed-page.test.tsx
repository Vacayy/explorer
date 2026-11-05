import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import type { TimelineChannel } from '../src/types'

/* 피드 화면 — '전체' 칩 숫자 = 사람 소스 글 수(목록 기준), '모두 읽음' = 지금 칩 범위로 한 번에(D-301) */
const ch = (id: string, count: number, unread: number): TimelineChannel =>
  ({ id, name: id, platform: id.split(':')[0] as TimelineChannel['platform'], count, unread, latest_at: '2026-11-04T00:00:00Z', preview: '' })
const CHANNELS = [ch('telegram:a', 120, 3), ch('youtube:b', 30, 2), ch('memo:c', 5, 0), { ...ch('narrative:all', 900, 4), platform: 'system' as const }]
const markAll = vi.fn()
const empty = { isLoading: false, isError: false, isFetching: false, isFetchingNextPage: false, hasNextPage: false, data: { pages: [{ items: [] }] }, refetch: () => {}, fetchNextPage: () => {} }

vi.mock('@/hooks/useFeed', () => ({
  useFeedChipCounts: () => ({ all: 54_021, telegram: 20_000, blog: 900 }),   // 훅이 스크랩을 뺀 문서 수
  useFeedTimeline: () => empty,
  useFeedDocuments: () => empty,
}))
vi.mock('@/hooks/useTimeline', () => ({
  useTimelineChannels: () => ({ isLoading: false, isError: false, data: { items: CHANNELS, total: 1055, total_unread: 9, until: '' }, refetch: () => {} }),
  useMarkChannelRead: () => ({ mutate: vi.fn(), isPending: false }),
  useMarkAllRead: () => ({ mutate: markAll, isPending: false }),
}))
vi.mock('@/hooks/useFeedTopics', () => ({ useFeedTopics: () => ({ stocks: [] }) }))
vi.mock('@/components/feed/DocumentSearch', () => ({ DocumentSearch: () => null }))
const { default: FeedPage } = await import('../src/components/feed/FeedPage')

beforeEach(() => markAll.mockReset())
afterEach(cleanup)
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}><FeedPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)
const chip = (label: string) => within(screen.getByRole('group', { name: '소스 종류' })).getByRole('button', { name: new RegExp(`^${label}`) })

it("counts the '전체' chip from followed human sources, not every document", () => {
  renderAt('/feed?reader_until=2026-11-04T09:00:00.000Z')
  expect(chip('전체').textContent).toBe('전체155')                // 120 + 30 + 5 — Explorer 산출물(900)·문서 전체(54,021) 제외
  expect(screen.getByPlaceholderText(/전체 수집 자료 54\.0천 건/)).toBeTruthy()   // 머리 검색칸은 문서 수 그대로
  expect(chip('텔레그램').textContent).toBe('텔레그램120')        // 타임라인 칩도 같은 기준(D-303) — 문서 수 20,000 아님
  expect(chip('유튜브').textContent).toBe('유튜브30')
  expect(chip('메모').textContent).toBe('메모5')
  expect(chip('블로그').textContent).toBe('블로그900')            // 문서 코퍼스 칩은 문서 수 그대로
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
