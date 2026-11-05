import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import { feedChip, highlightParts, isQuiet, isSearchView, unreadIds, usesTimeline } from '../src/lib/feed'
import { savedCounts } from '../src/lib/saved'
import { sourcesSummary } from '../src/lib/sources'
import { formatCountShort } from '../src/utils/format'
import type { FeedDocument, TimelineChannel, TimelineItem } from '../src/types'

/* ── 순수 규칙 ── */
const doc = (id: number, kind: string, key: string, over: Partial<FeedDocument> = {}): FeedDocument => ({
  id, source_type: kind, title: `글 ${id}`, url: '', published_at: '2026-11-04T02:00:00+00:00', summary: '요약', channel: key,
  channel_kind: kind, channel_key: key, content: null, images: [], enrich_model: null, entities: [], ...over,
})
const item = (id: number, kind: string, key: string): TimelineItem => ({
  id: `source:${id}`, kind: 'source', title: '', body: '', occurred_at: '', time_label: '', subject: '', period: null,
  evidence_count: null, ai_generated: false, to: '', document: doc(id, kind, key), links: [],
})
const channel = (id: string, unread: number, latest_at: string | null = '2026-11-04T00:00:00Z'): TimelineChannel =>
  ({ id, name: id, platform: id.split(':')[0] as TimelineChannel['platform'], count: 10, unread, latest_at, preview: '' })

it('reads the view and source chip from the URL, keeping old feed query names', () => {
  expect(isSearchView('?view=documents')).toBe(true)
  expect(isSearchView('?source=telegram')).toBe(true)          // 옛 /feed?source= 링크는 문서 검색
  expect(isSearchView('?channel_type=news&channel=telegram:a')).toBe(false)
  expect(feedChip('?channel_type=news')).toBe('news')
  expect(feedChip('?channel_type=bogus')).toBe('all')
  expect(feedChip('?channel_type=system')).toBe('system')
  expect([usesTimeline('all', ''), usesTimeline('telegram', ''), usesTimeline('news', ''), usesTimeline('blog', ''), usesTimeline('news', 'telegram:a')])
    .toEqual([true, true, false, false, true])
})

it('marks the newest n posts of each source unread, n = that source’s unread count', () => {
  const items = [item(1, 'telegram', 'a'), item(2, 'telegram', 'b'), item(3, 'telegram', 'a'), item(4, 'telegram', 'a'), item(5, 'blog', 'x')]
  const ids = unreadIds(items, [channel('telegram:a', 2), channel('telegram:b', 0), channel('blog:x', 5)])
  expect([...ids]).toEqual(['source:1', 'source:3', 'source:5'])
})

it('treats a source without new posts for 7 days as quiet', () => {
  const now = new Date('2026-11-05T00:00:00Z')
  expect(isQuiet('2026-10-06T00:00:00Z', now)).toBe(true)
  expect(isQuiet('2026-11-04T11:00:00Z', now)).toBe(false)
  expect(isQuiet(null, now)).toBe(true)
})

it('splits text into highlighted search hits without regex surprises', () => {
  expect(highlightParts('삼성 HBM4E와 hbm4', 'HBM4')).toEqual([
    { text: '삼성 ', hit: false }, { text: 'HBM4', hit: true }, { text: 'E와 ', hit: false }, { text: 'hbm4', hit: true },
  ])
  expect(highlightParts('a+b (c)', '(c)')).toEqual([{ text: 'a+b ', hit: false }, { text: '(c)', hit: true }])
  expect(highlightParts('그대로', '  ')).toEqual([{ text: '그대로', hit: false }])
})

it('shortens chip counts the way the board does', () => {
  expect([formatCountShort(25272), formatCountShort(11940), formatCountShort(1060), formatCountShort(614), formatCountShort(null)])
    .toEqual(['25.3천', '11.9천', '1.1천', '614', '-'])
})

it('counts saved items per type and summarises sources from the health payload only', () => {
  expect(savedCounts([{ kind: 'doc' }, { kind: 'doc' }, { kind: 'narrative' }])).toEqual({ all: 3, company: 0, doc: 2, narrative: 1, report: 0, chat: 0 })
  const s = sourcesSummary([
    { kind: 'telegram', docs_7d: 10, warning: false, collect_enabled: true },
    { kind: 'blog', docs_7d: 0, warning: true, collect_enabled: false },
    { kind: 'blog', docs_7d: 3, warning: false, collect_enabled: true },
  ])
  expect(s).toEqual({ total: 3, byKind: { telegram: 1, blog: 2 }, docs7d: 13, quiet: 1, collectOff: 1 })
})

/* ── 저장됨 화면 ── */
const saved = vi.hoisted(() => ({ state: { isLoading: false, isError: false, data: undefined as unknown, refetch: () => {} }, update: vi.fn(), remove: vi.fn() }))
vi.mock('@/hooks/useSaved', () => ({
  useSaved: () => saved.state,
  useRemoveSaved: () => ({ mutate: saved.remove }),
  useUpdateSavedNote: () => ({ mutate: saved.update }),
}))
const { default: SavedPage } = await import('../src/components/follow/SavedPage')

const ITEMS = [
  { id: 1, kind: 'doc', ref: '1', url: '/doc/1', title: 'EP 118', subtitle: 'AI Frontier', note: null, created_at: '2026-11-03 00:00:00' },
  { id: 2, kind: 'doc', ref: '2', url: '/doc/2', title: '빅테크 코멘트', subtitle: '디케이', note: '다시 볼 것', created_at: '2026-10-30 00:00:00' },
  { id: 3, kind: 'narrative', ref: 'CAPEX', url: '/narrative?topic=CAPEX', title: 'CAPEX', subtitle: 'v3', note: null, created_at: '2026-07-28 00:00:00' },
]
function Where() { const l = useLocation(); return <output data-testid="where">{l.pathname + l.search}</output> }
const renderSaved = (path = '/feed/saved') => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}>
  <Routes><Route path="/feed/saved" element={<><SavedPage /><Where /></>} /></Routes>
</MemoryRouter></TooltipProvider></QueryClientProvider>)

beforeEach(() => { saved.state = { isLoading: false, isError: false, data: ITEMS, refetch: () => {} }; saved.update.mockReset(); saved.remove.mockReset() })
afterEach(cleanup)

it('shows type tabs with counts and filters through the URL', () => {
  renderSaved()
  expect(screen.getByText('3건')).toBeTruthy()
  for (const label of ['전체 3', '기업 0', '문서 2', '내러티브 1', '리포트 0']) expect(screen.getByRole('radio', { name: label })).toBeTruthy()
  fireEvent.click(screen.getByRole('radio', { name: '내러티브 1' }))
  expect(screen.getByTestId('where').textContent).toBe('/feed/saved?kind=narrative')
  expect(screen.queryByText('EP 118')).toBeNull()
  expect(screen.getByText('CAPEX')).toBeTruthy()
})

it('shows a note only where one exists and opens the editor on demand', () => {
  renderSaved()
  expect(screen.queryAllByRole('textbox')).toHaveLength(0)        // 입력칸이 줄마다 떠 있지 않다
  expect(screen.getByText('다시 볼 것')).toBeTruthy()
  const row = screen.getByText('EP 118').closest('li')!
  fireEvent.click(within(row).getByRole('button', { name: 'EP 118 메모' }))
  const input = within(row).getByRole('textbox', { name: '메모' })
  fireEvent.change(input, { target: { value: '요약 확인' } })
  fireEvent.blur(input)
  expect(saved.update).toHaveBeenCalledWith({ id: 1, note: '요약 확인' })
  expect(screen.queryAllByRole('textbox')).toHaveLength(0)
})

it('covers empty, filtered-empty and error states', () => {
  saved.state = { ...saved.state, data: [] }
  renderSaved()
  expect(screen.getByText('아직 저장한 항목이 없어요')).toBeTruthy()
  cleanup()
  saved.state = { ...saved.state, data: ITEMS }
  renderSaved('/feed/saved?kind=report')
  expect(screen.getByText('이 유형의 저장 항목이 없습니다.')).toBeTruthy()
  cleanup()
  saved.state = { ...saved.state, data: undefined, isError: true }
  renderSaved()
  expect(screen.getByText('저장 목록을 불러오지 못했습니다')).toBeTruthy()
})
