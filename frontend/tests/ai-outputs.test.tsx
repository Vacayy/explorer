import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { TooltipProvider } from '../src/components/ui/tooltip'

/* 상단 바 'AI가 최근 만든 것'(D-325) — 종류 · 제목 · 시각 · 링크, 마지막으로 연 뒤 새 산출물이 있으면 점 */
const item = (id: string, kind: string, title: string, at: string, to: string) =>
  ({ id, kind, title, body: '', occurred_at: at, time_label: '', subject: '', period: null, evidence_count: null, ai_generated: true, to, document: null, links: [] })
const ITEMS = [
  item('narrative:1', 'narrative', '변압기 공급망', '2026-11-05T01:34:10+00:00', '/narrative?topic=x'),
  item('transcript:2', 'transcript', 'AMD · 2026 Q3 컨콜', '2026-11-05T01:06:06+00:00', '/follow/transcripts?t=2'),
]
vi.mock('@/hooks/useTimeline', () => ({
  useExplorerOutputs: () => ({ isLoading: false, isError: false, data: { items: ITEMS }, refetch: () => {} }),
}))
const { AiOutputsButton } = await import('../src/components/layout/AiOutputs')

beforeEach(() => localStorage.clear())
afterEach(cleanup)
const renderButton = () => render(<TooltipProvider><MemoryRouter><AiOutputsButton /></MemoryRouter></TooltipProvider>)

it('shows a dot until opened, then lists kind, title and link', () => {
  renderButton()
  fireEvent.click(screen.getByRole('button', { name: 'AI가 최근 만든 것 — 새 산출물 있음' }))
  expect(screen.getByRole('link', { name: /내러티브\s*변압기 공급망/ }).getAttribute('href')).toBe('/narrative?topic=x')
  expect(screen.getByRole('link', { name: /컨콜\s*AMD/ }).getAttribute('href')).toBe('/follow/transcripts?t=2')
  expect(screen.getByRole('link', { name: /Explorer 산출물 전체/ }).getAttribute('href')).toBe('/feed?channel_type=system')
  cleanup(); renderButton()                                  // 연 뒤에는 점이 없다
  expect(screen.getByRole('button', { name: 'AI가 최근 만든 것' })).toBeTruthy()
})

it('shows the dot again when something newer than the last visit arrives', () => {
  localStorage.setItem('explorer.aiOutputs.seenAt', '2026-11-05T01:00:00.000Z')
  renderButton()
  expect(screen.getByRole('button', { name: 'AI가 최근 만든 것 — 새 산출물 있음' })).toBeTruthy()
  cleanup(); localStorage.setItem('explorer.aiOutputs.seenAt', '2026-11-05T02:00:00.000Z'); renderButton()
  expect(screen.getByRole('button', { name: 'AI가 최근 만든 것' })).toBeTruthy()
})
