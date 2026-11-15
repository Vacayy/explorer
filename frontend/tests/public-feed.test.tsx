import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
const state = vi.hoisted(() => ({ error: null as Error | null, fetching: false, calls: vi.fn() }))
const channels = [
  { id: 'telegram:one', name: '첫 채널', platform: 'telegram', count: 1, latest_at: '2026-11-14', preview: '첫 자료' },
  { id: 'blog:two', name: '둘째 채널', platform: 'blog', count: 1, latest_at: '2026-11-14', preview: '둘째 자료' },
]
vi.mock('@/hooks/usePublicFeed', () => ({ usePublicFeed: (filters: {channel: string; page: number; until: string}) => {
  state.calls(filters)
  return { error: state.error, isFetching: state.fetching, fetchStatus: 'idle', refetch: vi.fn(), data: {
    channels, items: channels.filter(c => !filters.channel || c.id === filters.channel).map(c => ({id: c.id === 'telegram:one' ? 1 : 2})),
    page: filters.page, has_more: false, until: filters.until,
  } }
} }))
vi.mock('@/hooks/usePublishedDocument', () => ({ usePublishedDocument: (id: number) => ({ isFetching: false, fetchStatus: 'idle', error: null,
  data: { id, title: id === 1 ? '첫 자료' : '둘째 자료', source_type: 'web', content: `본문 ${id}`, content_kind: 'stored_text', attachments: [], url: null, published_at: null }, refetch: vi.fn() }) }))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => ({ status: 'anonymous' }) }))
vi.mock('@/hooks/useTimeline', () => ({
  useTimeline: () => { throw Error('private timeline') }, useTimelineChannels: () => { throw Error('private directory') },
  useMarkChannelRead: () => { throw Error('private read mutation') }, useMarkAllRead: () => { throw Error('private read mutation') },
}))
const { PublicContent } = await import('@/components/auth/PublicContent')
function Location() { const loc=useLocation();return <span aria-label="현재 주소">{loc.pathname}{loc.search}</span> }
function App() { return <MemoryRouter initialEntries={['/feed']}><PublicContent /><Location /></MemoryRouter> }
afterEach(() => {cleanup();state.error=null;state.fetching=false;vi.clearAllMocks()})
it('keeps source selection, original cards and document return without private hooks', () => {
 render(<App />)
 const directory=screen.getByRole('complementary',{name:'피드 소스 목록'})
 expect(screen.getByRole('heading',{name:'피드',level:1})).toBeTruthy()
 expect(screen.getAllByRole('article')).toHaveLength(2)
 fireEvent.click(within(directory).getByRole('button',{name:/둘째 채널/}))
 expect(state.calls).toHaveBeenLastCalledWith(expect.objectContaining({channel:'blog:two',page:1}))
 expect(screen.queryByRole('heading',{name:'첫 자료'})).toBeNull()
 expect(screen.getByRole('heading',{name:'둘째 자료'})).toBeTruthy()
 expect(screen.queryByText('모두 읽음')).toBeNull()
 expect(screen.queryByText('소스 관리')).toBeNull()
 fireEvent.click(screen.getByRole('link',{name:'둘째 자료'}))
 expect(screen.getByLabelText('현재 주소').textContent).toContain('/doc/2?')
 fireEvent.click(screen.getByRole('link',{name:'공개 문서 목록'}))
 expect(state.calls).toHaveBeenLastCalledWith(expect.objectContaining({channel:'blog:two'}))
 expect(screen.getByRole('button',{name:/둘째 채널/}).getAttribute('aria-pressed')).toBe('true')
 fireEvent.click(screen.getByRole('button',{name:'소스 목록으로'}))
 expect(screen.getByLabelText('현재 주소').textContent).toContain('reader_open=0')
})
it('hides cached directory and bodies on failure and revalidation', () => {
 const view=render(<App />)
 state.error=new Error('private details');view.rerender(<App />)
 expect(screen.queryByText('본문 1')).toBeNull()
 expect(screen.queryByText('첫 채널')).toBeNull()
 expect(view.container.textContent).not.toContain('private details')
 state.error=null;state.fetching=true;view.rerender(<App />)
 expect(screen.queryByRole('article')).toBeNull()
 expect(screen.queryByText('둘째 채널')).toBeNull()
})
