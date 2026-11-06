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
// 옛 원천(ai-activity) — 유튜브 AI 정리본은 타임라인에 없고, 같은 내러티브(주제·생성 시각 같음)는 한 번만 보인다
const ACTIVITY = [
  { type: 'youtube_digest', title: '빅테크 쇼크', topic: '빅테크 쇼크', code: null, question_id: null, doc_id: 77, created_at: '2026-11-05 01:20:00' },
  { type: 'narrative', title: '변압기 공급망', topic: 'x', code: null, question_id: null, doc_id: null, created_at: '2026-11-05 01:34:10' },
]
ITEMS[0].subject = 'x'
vi.mock('@/hooks/useTimeline', () => ({
  useExplorerOutputs: () => ({ isLoading: false, isError: false, data: { items: ITEMS }, refetch: () => {} }),
  useAiActivity: () => ({ isLoading: false, isError: false, data: ACTIVITY, refetch: () => {} }),
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
  expect(screen.getAllByRole('link', { name: /변압기 공급망/ })).toHaveLength(1)
  const links = screen.getAllByRole('link').map(a => a.getAttribute('href'))
  expect(links.slice(0, 3)).toEqual(['/narrative?topic=x', '/doc/77?reading=digest', '/follow/transcripts?t=2'])  // 최신순
  expect(screen.getByRole('link', { name: /유튜브 요약\s*빅테크 쇼크/ })).toBeTruthy()
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
