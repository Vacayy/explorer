import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { ApiError } from '@/api/errors'
import type { PublishedDocumentList } from '@/types'

const state = vi.hoisted(() => ({ data: undefined as PublishedDocumentList | undefined, error: null as Error | null,
  isFetching: false, fetchStatus: 'idle', refetch: vi.fn(), calls: vi.fn() }))
vi.mock('@/hooks/usePublishedDocuments', () => ({ usePublishedDocuments: (...args: unknown[]) => { state.calls(...args); return state } }))
const { PublicContent } = await import('@/components/auth/PublicContent')
function Location() { const loc = useLocation(); return <span aria-label="현재 주소">{loc.pathname}{loc.search}</span> }
function renderFeed(path = '/feed?view=documents') { return render(<MemoryRouter initialEntries={[path]}><PublicContent /><Location /></MemoryRouter>) }
afterEach(() => { cleanup(); state.data = undefined; state.error = null; state.isFetching = false; state.fetchStatus = 'idle'; vi.clearAllMocks() })
const data = (): PublishedDocumentList => ({ items: [{ id: 12, title: '승인 자료', source_type: 'web', published_at: null, snippet: '공개된 보관 본문' }], next_cursor: 'opaque-next' })

it('renders public feed results as plain text with only document links and no global count', () => {
  state.data = data(); state.data.items[0].snippet = '![unapproved](https://tracker.test/img) <script>not markup</script>'
  renderFeed()
  expect(screen.getByRole('heading', { name: '공개 문서' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '승인 자료' }).getAttribute('href')).toBe('/doc/12')
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.getByText(/not markup/)).toBeTruthy()
  expect(screen.queryByText(/총.*건/)).toBeNull()
  expect(state.calls).toHaveBeenLastCalledWith('', null, true)
})

it('keeps search and pagination in URL and resets pagination on new search', () => {
  state.data = data(); renderFeed('/feed?q=memory')
  fireEvent.click(screen.getByRole('link', { name: '다음' }))
  expect(screen.getByLabelText('현재 주소').textContent).toBe('/feed?q=memory&cursor=opaque-next')
  expect(state.calls).toHaveBeenLastCalledWith('memory', 'opaque-next', true)
  fireEvent.click(screen.getByRole('button', { name: '이전' }))
  expect(screen.getByLabelText('현재 주소').textContent).toBe('/feed?q=memory')
  fireEvent.click(screen.getByRole('link', { name: '다음' }))
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: '  new query  ' } })
  fireEvent.submit(screen.getByRole('search'))
  expect(screen.getByLabelText('현재 주소').textContent).toBe('/feed?q=new+query')
  expect(state.calls).toHaveBeenLastCalledWith('new query', null, true)
})

it('returns a directly opened later page to the first public page', () => {
  state.data = { items: [], next_cursor: null }; renderFeed('/feed?q=memory&cursor=opaque-next')
  fireEvent.click(screen.getByRole('button', { name: '이전' }))
  expect(screen.getByLabelText('현재 주소').textContent).toBe('/feed?q=memory')
})

it('continues an empty search segment without claiming there are no matches', () => {
  state.data = { items: [], next_cursor: 'opaque-next' }; renderFeed('/feed?q=memory')
  expect(screen.getByText('아직 일치하는 문서가 없습니다. 계속 검색할 수 있습니다.')).toBeTruthy()
  expect(screen.queryByText('검색 결과가 없습니다.')).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: '다음' }))
  expect(state.calls).toHaveBeenLastCalledWith('memory', 'opaque-next', true)
})

it('restarts an expired cursor with the same search instead of retrying the expired token', () => {
  state.data = data(); state.error = new ApiError('private token details', 400)
  renderFeed('/feed?q=memory&cursor=expired')
  expect(screen.queryByText('승인 자료')).toBeNull()
  expect(screen.getByRole('alert').textContent).not.toContain('private token')
  expect(screen.getByRole('link', { name: '검색 처음부터' }).getAttribute('href')).toBe('/feed?q=memory')
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
  expect(screen.getByLabelText('현재 주소').textContent).toBe('/feed?q=memory')
  expect(state.refetch).not.toHaveBeenCalled()
})

it('hides stale results during reload, errors and paused network; never mistakes failures for no results', () => {
  state.data = data(); const view = renderFeed()
  state.isFetching = true; view.rerender(<MemoryRouter><PublicContent /><Location /></MemoryRouter>)
  expect(screen.queryByText('승인 자료')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('불러오는 중')
  state.isFetching = false; state.error = new ApiError('sensitive implementation detail', 503)
  view.rerender(<MemoryRouter><PublicContent /><Location /></MemoryRouter>)
  expect(screen.queryByText('승인 자료')).toBeNull()
  expect(screen.queryByText('검색 결과가 없습니다.')).toBeNull()
  expect(screen.getByRole('alert').textContent).not.toContain('sensitive')
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' })); expect(state.refetch).toHaveBeenCalledOnce()
  state.error = null; state.fetchStatus = 'paused'
  view.rerender(<MemoryRouter><PublicContent /><Location /></MemoryRouter>)
  expect(screen.queryByText('승인 자료')).toBeNull()
  expect(screen.getByRole('alert').textContent).toContain('네트워크')
})

it('distinguishes empty public feed and zero search results; disables malformed URL reads', () => {
  state.data = { items: [], next_cursor: null }
  const view = renderFeed()
  expect(screen.getByText('아직 공개된 문서가 없습니다.')).toBeTruthy()
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'no-match' } }); fireEvent.submit(screen.getByRole('search'))
  expect(screen.getByText('검색 결과가 없습니다.')).toBeTruthy()
  view.unmount(); renderFeed('/feed?cursor=' + 'x'.repeat(2049))
  expect(screen.getByRole('alert').textContent).toContain('검색 주소')
  expect(state.calls).toHaveBeenLastCalledWith('', 'x'.repeat(2049), false)
})

it('preserves company return through search edits, paging and document links', () => {
 const company='/analyze/005930/summary?price_range=1y&sector=semiconductor'
 state.data=data();renderFeed('/feed?'+new URLSearchParams({q:'company',company_return:company}))
 expect(screen.getByRole('link',{name:'기업 요약으로'}).getAttribute('href')).toBe(company)
 fireEvent.click(screen.getByRole('link',{name:'다음'}))
 const current=screen.getByLabelText('현재 주소').textContent!
 const document=new URL(screen.getByRole('link',{name:'승인 자료'}).getAttribute('href')!,'https://local.invalid')
 expect(document.searchParams.get('return_to')).toBe(current)
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'new company'}});fireEvent.submit(screen.getByRole('search'))
 const changed=new URL(screen.getByLabelText('현재 주소').textContent!,'https://local.invalid')
 expect(changed.searchParams.get('cursor')).toBeNull()
 expect(changed.searchParams.get('company_return')).toBe(company)
 expect(changed.searchParams.get('q')).toBe('new company')
})
