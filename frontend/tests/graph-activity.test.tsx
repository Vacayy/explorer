import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'

// D-308 — 옛 /knowledge의 '인과 그래프 업데이트'를 Thesis › 그래프 아래로 되살림
vi.mock('@/hooks/useWorld', () => ({ useNarrativeTopics: () => ({ topics: new Set(['AI']) }) }))
const get = vi.fn(async () => ({ data: [] }))
vi.mock('@/api/client', () => ({ default: { get } }))
const { GraphActivitySection } = await import('../src/components/explore/GraphActivitySection')
afterEach(() => { cleanup(); get.mockClear() })
const open = () => fireEvent.click(screen.getByRole('button', { name: '인과 그래프 업데이트' }))

function renderWith(data: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(['spine', 'causal', 'activity'], data)
  return render(<QueryClientProvider client={qc}><TooltipProvider><MemoryRouter><GraphActivitySection /></MemoryRouter></TooltipProvider></QueryClientProvider>)
}

it('links nodes with a narrative to the narrative and others to the ontology focus', () => {
  renderWith([
    { id: 1, name: 'AI', type: 'sector', is_new: false, new_edges: 91, beneficiaries: [{ stock_code: '068270', name: '셀트리온', rs_short: 95 }] },
    { id: 2, name: '관세', type: 'policy', is_new: true, new_edges: 3, beneficiaries: [] },
  ])
  open()
  expect(screen.getByText('AI').closest('a')!.getAttribute('href')).toBe('/narrative?topic=AI')
  expect(screen.getByText('관세').closest('a')!.getAttribute('href')).toBe('/knowledge/ontology?focus=2')
  expect(screen.getByText('갱신 +91')).toBeTruthy()
  expect(screen.getByText('신규')).toBeTruthy()
  expect(screen.getByText('수혜 후보: 셀트리온 (RS 95)')).toBeTruthy()
})

it('says so when nothing changed in 7 days', () => {
  renderWith([])
  open()
  expect(screen.getByText('최근 7일 인과 그래프 업데이트가 없습니다.')).toBeTruthy()
})

it('stays folded and does not call the slow API until opened', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><TooltipProvider><MemoryRouter><GraphActivitySection /></MemoryRouter></TooltipProvider></QueryClientProvider>)
  expect(get).not.toHaveBeenCalled()
  expect(screen.queryByText('최근 7일 인과 그래프 업데이트가 없습니다.')).toBeNull()
  open()
  expect(await screen.findByText('최근 7일 인과 그래프 업데이트가 없습니다.')).toBeTruthy()
  expect(get).toHaveBeenCalledTimes(1)
})
