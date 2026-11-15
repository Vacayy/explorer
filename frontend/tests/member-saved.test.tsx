import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import api from '@/api/client'

const state = vi.hoisted(() => ({ real: false, access: { status: 'member', session: { user: { id: 'A' }, csrf_token: 'csrf-A' }, retry: vi.fn() }, list: {} as Record<string, unknown>,
  save: { mutate: vi.fn(), reset: vi.fn(), isPending: false, error: null as unknown }, update: { mutate: vi.fn(), reset: vi.fn(), isPending: false, error: null as unknown },
  remove: { mutate: vi.fn(), reset: vi.fn(), isPending: false, error: null as unknown }, read: vi.fn() }))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => state.access }))
vi.mock('@/hooks/useMemberSaved', () => ({
  useMemberSaved: (offset?: number, docId?: number) => { if (state.real) return actual.useMemberSaved(offset, docId); state.read(...[offset, docId].filter(value => value !== undefined)); return state.list },
  useSaveMemberDocument: () => state.real ? actual.useSaveMemberDocument() : state.save, useUpdateMemberSavedNote: () => state.real ? actual.useUpdateMemberSavedNote() : state.update, useDeleteMemberSaved: () => state.real ? actual.useDeleteMemberSaved() : state.remove,
}))
const { MemberSavedPage } = await import('@/components/follow/MemberSavedPage')
const { MemberDocumentSaveButton } = await import('@/components/shared/MemberDocumentSaveButton')
const actual = await vi.importActual<typeof import('@/hooks/useMemberSaved')>('@/hooks/useMemberSaved')
const ready = (data: unknown) => ({ data, error: null, isPending: false, isFetching: false, fetchStatus: 'idle', refetch: vi.fn() })
const row = { id: 7, doc_id: 99, title: 'Approved title', url: '/doc/99', available: true, status: 'available' as const, current_url: null, note: 'A private note', created_at: '2026-11-15' }
function setup() {
  state.real = false; state.access.status = 'member'; state.access.session.user.id = 'A'; state.access.session.csrf_token = 'csrf-A'
  state.list = ready({ items: [row], next_offset: null }); state.save.error = null; state.update.error = null; state.remove.error = null
}
function Location() { const location = useLocation(); return <output aria-label="URL">{location.search}</output> }
function show(button = false) { return render(<MemoryRouter>{button ? <MemberDocumentSaveButton docId={99} /> : <MemberSavedPage />}<Location /></MemoryRouter>) }
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks() })
it('gates list and save button before member queries mount', () => {
  setup(); state.access.status = 'anonymous'; const page = show()
  expect(screen.getByRole('link', { name: 'Google 로그인' }).getAttribute('href')).toContain('feed%2Fsaved')
  expect(state.read).not.toHaveBeenCalled(); page.unmount(); show(true)
  expect(screen.getByRole('link', { name: '로그인하고 문서 저장' }).getAttribute('href')).toContain('doc%2F99')
  expect(state.read).not.toHaveBeenCalled()
})
it('withholds unavailable titles and links while preserving owned note editing and failed writes', () => {
  setup(); state.list = ready({ items: [{ ...row, available: false, status: 'unavailable', title: 'REVOKED CANARY', url: '/doc/99' }], next_offset: null })
  state.update.error = new Error('failed'); const page = show()
  expect(screen.queryByText('REVOKED CANARY')).toBeNull()
  expect(screen.queryByRole('link', { name: 'REVOKED CANARY' })).toBeNull()
  expect(screen.getByText('A private note')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '메모 편집' }))
  fireEvent.change(screen.getByLabelText('내 문서 메모'), { target: { value: 'Edited private note' } })
  fireEvent.click(screen.getByRole('button', { name: '메모 저장' }))
  expect(state.update.mutate.mock.calls[0][0]).toEqual({ id: 7, note: 'Edited private note' })
  expect((screen.getByLabelText('내 문서 메모') as HTMLTextAreaElement).value).toBe('Edited private note')
  expect(screen.getByRole('alert').textContent).toContain('입력 내용은 유지')
  fireEvent.click(screen.getByRole('button', { name: '취소' }))
  fireEvent.click(screen.getByRole('button', { name: '저장 해제' }))
  expect(state.remove.mutate).not.toHaveBeenCalled()
  fireEvent.click(screen.getAllByRole('button', { name: '저장 해제' }).at(-1)!)
  expect(state.remove.mutate.mock.calls[0][0]).toBe(7)
  state.remove.error = new Error('failed'); page.rerender(<MemoryRouter><MemberSavedPage /></MemoryRouter>)
  expect(screen.getByText('A private note')).toBeTruthy()
  expect(screen.getByRole('alert').textContent).toContain('해제하지 못했습니다')
})
it('hides all cached metadata and notes on every read failure including 503 and permission failures', () => {
  for (const status of [401,403,503]) {
    setup(); state.list = { ...ready({ items: [row], next_offset: 20 }), error: { response: { status } } }
    const page = show(); expect(screen.queryByText(row.title)).toBeNull(); expect(screen.queryByText(row.note)).toBeNull()
    expect(screen.getByRole('button', { name: '다음 페이지' }).hasAttribute('disabled')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' })); expect(state.list.refetch).toHaveBeenCalledOnce(); page.unmount()
  }
})
it('resets draft and confirmation on account transition and keeps pagination in the URL', () => {
  setup(); state.list = ready({ items: [row], next_offset: 20 }); const page = show()
  fireEvent.click(screen.getByRole('button', { name: '메모 편집' }))
  fireEvent.change(screen.getByLabelText('내 문서 메모'), { target: { value: 'A unsaved CANARY' } })
  state.access.session.user.id = 'B'; state.list = ready({ items: [], next_offset: null })
  page.rerender(<MemoryRouter><MemberSavedPage /><Location /></MemoryRouter>)
  expect(screen.queryByLabelText('내 문서 메모')).toBeNull()
  expect(screen.queryByText('A unsaved CANARY')).toBeNull()
  state.list = ready({ items: [{ ...row, note: 'B note' }], next_offset: 20 })
  page.rerender(<MemoryRouter><MemberSavedPage /><Location /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '다음 페이지' }))
  expect(screen.getByLabelText('URL').textContent).toBe('?offset=20')
  expect(state.read).toHaveBeenLastCalledWith(20)
})
it('uses document-filtered toggle, confirms removal and refuses a cached status on failed verification', () => {
  setup(); state.list = ready({ items: [], next_offset: null }); const button = show(true)
  expect(state.read).toHaveBeenLastCalledWith(0,99)
  fireEvent.click(screen.getByRole('button', { name: '내 문서에 저장' })); expect(state.save.mutate.mock.calls[0][0]).toEqual({ doc_id: 99 })
  state.list = ready({ items: [row], next_offset: null }); button.rerender(<MemoryRouter><MemberDocumentSaveButton docId={99} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '저장됨 · 해제' })); expect(state.remove.mutate).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '저장 해제' })); expect(state.remove.mutate.mock.calls[0][0]).toBe(7)
  state.list = { ...ready({ items: [row], next_offset: null }), error: new Error('read budget') }
  button.rerender(<MemoryRouter><MemberDocumentSaveButton docId={99} /></MemoryRouter>)
  expect(screen.queryByRole('button', { name: '저장됨 · 해제' })).toBeNull()
  expect(screen.getByRole('button', { name: '저장 상태 다시 확인' })).toBeTruthy()
})
it('shows loading and empty states without inventing saved entries', () => {
  setup(); state.list = { ...ready(undefined), isPending: true, fetchStatus: 'fetching' }; const loading = show()
  expect(screen.getByRole('status', { name: '데이터 불러오는 중' })).toBeTruthy(); loading.unmount()
  state.list = ready({ items: [], next_offset: null }); show()
  expect(screen.getByText(/아직 저장한 문서가 없습니다/)).toBeTruthy()
})
it('real hooks scope reads by account, send CSRF on mutations and only use member routes', async () => {
  setup()
  const get = vi.spyOn(api,'get').mockResolvedValue({ data: { items: [], next_offset: null } })
  const post = vi.spyOn(api,'post').mockResolvedValue({ data: row })
  const patch = vi.spyOn(api,'patch').mockResolvedValue({ data: { ok: true } })
  const remove = vi.spyOn(api,'delete').mockResolvedValue({ data: { ok: true } })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function Harness() {
    const q = actual.useMemberSaved(0,99); const save = actual.useSaveMemberDocument(); const update = actual.useUpdateMemberSavedNote(); const del = actual.useDeleteMemberSaved()
    return <><span>{q.data ? 'ready' : 'loading'}</span><button onClick={() => save.mutate({ doc_id: 99 })}>save</button><button onClick={() => update.mutate({ id: 7, note: 'mine' })}>patch</button><button onClick={() => del.mutate(7)}>delete</button></>
  }
  const view = render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
  await screen.findByText('ready')
  expect(get.mock.calls[0][0]).toBe('/api/member/saved')
  expect(get.mock.calls[0][1]?.params).toEqual({ offset: 0, limit: 20, doc_id: 99 })
  fireEvent.click(screen.getByText('save')); fireEvent.click(screen.getByText('patch')); fireEvent.click(screen.getByText('delete'))
  await waitFor(() => expect(remove).toHaveBeenCalled())
  const config = { withCredentials: true, headers: { 'X-CSRF-Token': 'csrf-A' } }
  expect(post).toHaveBeenCalledWith('/api/member/saved', { doc_id: 99 }, config)
  expect(patch).toHaveBeenCalledWith('/api/member/saved/7', { note: 'mine' }, config)
  expect(remove).toHaveBeenCalledWith('/api/member/saved/7', config)
  expect(client.getQueryCache().getAll().some(q => JSON.stringify(q.queryKey) === JSON.stringify(['member','A','member','saved-documents',0,99]))).toBe(true)
  state.access.session.user.id = 'B'; state.access.session.csrf_token = 'csrf-B'
  view.rerender(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
  await waitFor(() => expect(client.getQueryCache().getAll().some(q => q.queryKey[1] === 'B')).toBe(true))
  view.unmount(); client.clear()
})

it('hides metadata while revalidating and blanks the whole list after mutation authorization loss', () => {
  setup(); state.list = { ...ready({ items: [row], next_offset: null }), isFetching: true, fetchStatus: 'fetching' }; const pending = show()
  expect(screen.queryByText(row.title)).toBeNull(); expect(screen.queryByText(row.note)).toBeNull(); pending.unmount()
  state.list = ready({ items: [row, { ...row, id: 8, doc_id: 100, note: 'Other private note' }], next_offset: null })
  const view = show(); fireEvent.click(screen.getAllByRole('button', { name: '메모 편집' })[0])
  fireEvent.click(screen.getByRole('button', { name: '메모 저장' }))
  act(() => state.update.mutate.mock.calls[0][1].onError({ response: { status: 403 } }))
  expect(screen.queryByText(row.title)).toBeNull(); expect(screen.queryByText('Other private note')).toBeNull()
  expect(screen.queryByLabelText('내 문서 메모')).toBeNull(); expect(screen.getByText(/로그인 권한을 다시 확인/)).toBeTruthy(); view.unmount()
  state.list = ready({ items: [], next_offset: null }); show(true)
  fireEvent.click(screen.getByRole('button', { name: '내 문서에 저장' }))
  act(() => state.save.mutate.mock.calls[0][1].onError({ response: { status: 401 } }))
  expect(screen.queryByRole('button', { name: '내 문서에 저장' })).toBeNull()
  expect(screen.getByRole('button', { name: '로그인 권한 다시 확인' })).toBeTruthy()
})
it('retains an available document link even when its approved title is blank', () => {
  setup(); state.list = ready({ items: [{ ...row, title: '' }], next_offset: null }); show()
  expect(screen.getByRole('link', { name: '제목 없는 문서' }).getAttribute('href')).toBe('/doc/99')
})
it('late A mutation completion never carries its draft or invalidation into B', async () => {
  setup(); state.real = true
  let resolvePatch!: (value: { data: { ok: boolean } }) => void
  vi.spyOn(api, 'patch').mockImplementation(() => new Promise(resolve => { resolvePatch = resolve }))
  const get = vi.spyOn(api, 'get').mockImplementation(async () => ({ data: { items: [{ ...row, note: state.access.session.user.id + ' note' }], next_offset: null } }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const view = render(<QueryClientProvider client={client}><MemoryRouter><MemberSavedPage /></MemoryRouter></QueryClientProvider>)
  await screen.findByText('A note')
  fireEvent.click(screen.getByRole('button', { name: '메모 편집' }))
  fireEvent.change(screen.getByLabelText('내 문서 메모'), { target: { value: 'A pending draft CANARY' } })
  fireEvent.click(screen.getByRole('button', { name: '메모 저장' }))
  await waitFor(() => expect(resolvePatch).toBeTypeOf('function'))
  state.access.session.user.id = 'B'; state.access.session.csrf_token = 'csrf-B'
  view.rerender(<QueryClientProvider client={client}><MemoryRouter><MemberSavedPage /></MemoryRouter></QueryClientProvider>)
  await screen.findByText('B note'); const beforeCompletionReads = get.mock.calls.length
  expect(screen.queryByLabelText('내 문서 메모')).toBeNull()
  await act(async () => resolvePatch({ data: { ok: true } }))
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['member','A','member','saved-documents'] }))
  expect(get.mock.calls.length).toBe(beforeCompletionReads)
  expect(screen.getByText('B note')).toBeTruthy()
  expect(screen.queryByText('A pending draft CANARY')).toBeNull()
  expect(screen.queryByLabelText('내 문서 메모')).toBeNull()
  view.unmount(); client.clear(); state.real = false
})

it('distinguishes changed versions and links only to the validated current public document', () => {
  setup(); state.list = ready({ items: [{ ...row, status: 'changed', available: false, title: 'OLD TITLE CANARY', url: null, current_url: '/doc/99' }], next_offset: null })
  const page = show()
  expect(screen.getByText('저장 이후 내용이 변경된 문서')).toBeTruthy()
  expect(screen.queryByText('OLD TITLE CANARY')).toBeNull()
  expect(screen.getByRole('link', { name: '현재 공개본 보기' }).getAttribute('href')).toBe('/doc/99')
  expect(screen.getByText('A private note')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '메모 편집' }))
  expect((screen.getByLabelText('내 문서 메모') as HTMLTextAreaElement).value).toBe('A private note')
  state.list = ready({ items: [{ ...row, status: 'changed', available: false, title: null, url: null, current_url: 'https://outside.test/doc/99' }], next_offset: null })
  page.rerender(<MemoryRouter><MemberSavedPage /></MemoryRouter>)
  expect(screen.queryByRole('link', { name: '현재 공개본 보기' })).toBeNull(); page.unmount()
  state.list = ready({ items: [{ ...row, status: 'changed', available: false, title: null, url: null, current_url: '/doc/99' }], next_offset: null })
  show(true)
  expect(screen.getByRole('button', { name: '이전 공개본 저장됨 · 해제' })).toBeTruthy()
  expect(screen.getByText(/현재 공개본은 저장한 버전과 다릅니다/)).toBeTruthy()
  expect(state.save.mutate).not.toHaveBeenCalled()
})
