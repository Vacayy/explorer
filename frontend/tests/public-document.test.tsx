import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ApiError } from '@/api/errors'
import type { PublishedDocument } from '@/types'

const state = vi.hoisted(() => ({ data: undefined as PublishedDocument | undefined, error: null as Error | null,
  isFetching: false, fetchStatus: 'idle', refetch: vi.fn() }))
vi.mock('@/hooks/usePublishedDocument', () => ({ usePublishedDocument: () => state }))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => ({ status: 'anonymous', session: undefined, retry: vi.fn() }) }))
const { PublicDocumentPage } = await import('@/components/doc/PublicDocumentPage')
const { PublicContent } = await import('@/components/auth/PublicContent')
function document(overrides: Partial<PublishedDocument> = {}): PublishedDocument {
  return { id: 12, title: '승인 문서', source_type: 'web', url: null, published_at: null,
    content: '보관된 내용', content_kind: 'stored_markdown', attachments: [], ...overrides }
}
afterEach(() => { cleanup(); state.data = undefined; state.error = null; state.isFetching = false; state.fetchStatus = 'idle'; vi.clearAllMocks() })

it('routes public docs to the approved reader without personal document tools', () => {
  state.data = document()
  render(<MemoryRouter initialEntries={['/doc/12']}><PublicContent /></MemoryRouter>)
  expect(screen.getByRole('heading', { name: '승인 문서' })).toBeTruthy()
  expect(screen.getByRole('region', { name: '보관된 본문' }).textContent).toContain('보관된 내용')
  expect(screen.queryByRole('tab')).toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
})

it('suppresses inline images and unsafe links; serves only document-bound approved attachments', () => {
  state.data = document({ url: 'https://user:pass@example.com',
    content: '![tracker](https://tracker.test/image.png) ![private](/media/private.png) [safe](https://example.com/page) [internal](/doc/99) [media](/media/private) [credential](https://user:pass@example.com) [script](javascript:alert)',
    attachments: [
      { id: 0, media_type: 'image/png', size: 20, url: '/api/public/documents/12/attachments/0' },
      { id: 1, media_type: 'application/pdf', size: 30, url: '/api/public/documents/12/attachments/1' },
      { id: 2, media_type: 'image/png', size: 20, url: 'https://tracker.test/image.png' },
      { id: 3, media_type: 'image/png', size: 20, url: '/api/public/documents/99/attachments/3' },
      { id: 4, media_type: 'image/png', size: 20, url: '/media/private.png' },
    ],
  })
  render(<MemoryRouter><PublicDocumentPage docId="12" /></MemoryRouter>)
  expect(screen.getAllByRole('img')).toHaveLength(1)
  expect(screen.getByRole('img').getAttribute('src')).toBe('/api/public/documents/12/attachments/0')
  expect(screen.getAllByRole('link')).toHaveLength(6)
  expect(screen.getByRole('link', { name: '이 문서로 체험 채팅' }).getAttribute('href')).toBe('/chat?doc=12')
  expect(screen.getByRole('link', { name: 'safe' }).getAttribute('rel')).toContain('noreferrer')
  expect(screen.getByRole('link', { name: /PDF 첨부/ }).hasAttribute('download')).toBe(true)
  fireEvent.error(screen.getByRole('img'))
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('불러올 수 없습니다')
})

it('handles loading, image-only and literal stored text', () => {
  const view = render(<MemoryRouter><PublicDocumentPage docId="12" /></MemoryRouter>)
  expect(screen.getByRole('status').textContent).toContain('불러오는 중')
  state.data = document({ content: '', attachments: [{ id: 0, media_type: 'image/webp', size: 3, url: '/api/public/documents/12/attachments/0' }] })
  view.rerender(<MemoryRouter><PublicDocumentPage docId="12" /></MemoryRouter>)
  expect(screen.getByText(/아래 첨부를 확인/)).toBeTruthy()
  expect(screen.getByRole('img')).toBeTruthy()
  state.data = document({ content_kind: 'stored_text', content: '[literal](https://example.com)' })
  view.rerender(<MemoryRouter><PublicDocumentPage docId="12" /></MemoryRouter>)
  expect(screen.getByText('[literal](https://example.com)')).toBeTruthy()
  expect(screen.getByRole('link', { name: '공개 문서 목록' }).getAttribute('href')).toBe('/feed')
})

it('hides cached bodies for revocation and unavailable services, with explicit retry', () => {
  state.data = document()
  state.error = new ApiError('private internal reason', 404)
  const view = render(<MemoryRouter><PublicDocumentPage docId="12" /></MemoryRouter>)
  expect(screen.getByText('공개된 문서를 찾을 수 없습니다.')).toBeTruthy()
  expect(screen.queryByText('승인 문서')).toBeNull()
  expect(view.container.textContent).not.toContain('private internal reason')
  state.error = new ApiError('private internal reason', 503)
  view.rerender(<MemoryRouter><PublicDocumentPage docId="12" /></MemoryRouter>)
  expect(screen.queryByText('승인 문서')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
  expect(state.refetch).toHaveBeenCalledOnce()
  state.error = null; state.isFetching = true
  view.rerender(<MemoryRouter><PublicDocumentPage docId="12" /></MemoryRouter>)
  expect(screen.queryByText('승인 문서')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('불러오는 중')
})

it('does not show cached content for malformed document identifiers', () => {
  state.data = document()
  render(<MemoryRouter><PublicDocumentPage docId="9007199254740992" /></MemoryRouter>)
  expect(screen.queryByText('승인 문서')).toBeNull()
  expect(screen.getByText('공개된 문서를 찾을 수 없습니다.')).toBeTruthy()
})

it('keeps search return after direct open and revocation while hiding cached text', () => {
 const feed='/feed?'+new URLSearchParams({q:'company',cursor:'opaque',company_return:'/analyze/005930/summary?price_range=1y'})
 state.data=document();state.error=new ApiError('revoked',404)
 render(<MemoryRouter initialEntries={['/doc/12?'+new URLSearchParams({return_to:feed})]}><PublicDocumentPage docId="12"/></MemoryRouter>)
 expect(screen.queryByText('보관된 내용')).toBeNull()
 expect(screen.getByRole('link',{name:'공개 문서 목록'}).getAttribute('href')).toBe(feed)
})
