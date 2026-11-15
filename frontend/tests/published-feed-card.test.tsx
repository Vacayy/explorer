import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ApiError } from '@/api/errors'
import type { PublishedDocument } from '@/types'

const state = vi.hoisted(() => ({ data: undefined as PublishedDocument | undefined, error: null as Error | null,
  isFetching: false, fetchStatus: 'idle', refetch: vi.fn() }))
vi.mock('@/hooks/usePublishedDocument', () => ({ usePublishedDocument: () => state }))
vi.mock('@/components/study/AddToStudy', () => ({ AddToStudy: () => { throw Error('Private study mounted') } }))
vi.mock('@/components/study/StudyButton', () => ({ StudyButton: () => { throw Error('Private study mounted') } }))
const { PublishedDocumentCard } = await import('@/components/feed/PublishedDocumentCard')
afterEach(() => { cleanup(); state.data = undefined; state.error = null; state.isFetching = false; state.fetchStatus = 'idle' })
const doc: PublishedDocument = { id: 12, title: '승인 자료', source_type: 'web', url: 'https://www.sec.gov/example',
  published_at: '2026-11-14T00:00:00Z', content_kind: 'stored_markdown',
  content: '보관된 전체 본문\n\n![tracking](https://tracking.test/img) [private](/media/private)', attachments: [] }

it('uses the original feed card with approved full text and preserves search return, without private tools', () => {
  state.data = doc
  render(<MemoryRouter><PublishedDocumentCard id={12} returnTo="/feed?q=SEC" /></MemoryRouter>)
  expect(screen.getByRole('article').className).toBe('feed-post-row')
  expect(screen.getByRole('heading', { name: '승인 자료' })).toBeTruthy()
  expect(screen.getByText('보관된 전체 본문')).toBeTruthy()
  expect(screen.getByRole('link', { name: '자료 상세' }).getAttribute('href')).toBe('/doc/12?return_to=%2Ffeed%3Fq%3DSEC')
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.queryByRole('link', { name: 'private' })).toBeNull()
  expect(screen.getByRole('link', { name: /원문.*사이트/ }).getAttribute('href')).toBe(doc.url)
})

it('removes cached title and body while validating, on failure, revocation, and offline', () => {
  state.data = doc
  const view = render(<MemoryRouter><PublishedDocumentCard id={12} /></MemoryRouter>)
  expect(screen.getByText('보관된 전체 본문')).toBeTruthy()
  for (const failure of [new ApiError('internal', 404), new ApiError('internal', 503)]) {
    state.error = failure
    view.rerender(<MemoryRouter><PublishedDocumentCard id={12} /></MemoryRouter>)
    expect(screen.queryByText('보관된 전체 본문')).toBeNull()
    expect(screen.queryByText('승인 자료')).toBeNull()
  }
  state.error = null; state.isFetching = true
  view.rerender(<MemoryRouter><PublishedDocumentCard id={12} /></MemoryRouter>)
  expect(screen.queryByText('승인 자료')).toBeNull()
  state.isFetching = false; state.fetchStatus = 'paused'
  view.rerender(<MemoryRouter><PublishedDocumentCard id={12} /></MemoryRouter>)
  expect(screen.queryByText('보관된 전체 본문')).toBeNull()
})
