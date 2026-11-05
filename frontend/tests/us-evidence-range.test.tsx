import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'

/* 미국 자료 탭 기간(D-306 3) — URL ?from=&to=, 옛 ?day= 는 하루 기간, 막대 누르기 = 그날, 1·2·4주. 요약은 누를 때만 */
const days = Array.from({ length: 30 }, (_, i) => ({ date: new Date(Date.UTC(2026, 9, 6 + i)).toISOString().slice(0, 10), count: i % 3 }))
const calls: Record<string, unknown>[] = []
vi.mock('@/hooks/useCompanyEvidence', () => ({
  useCompanyEvidence: (p: Record<string, unknown>) => {
    calls.push(p)
    return { isPending: false, isError: false, isFetching: false, refetch: () => {}, data: { items: [], total: 0, has_more: false, coverage: [], undated_count: 0, uncertain_count: 0, flow: { days, sources: [{ source: 'telegram', count: 9 }] } } }
  },
}))
vi.mock('@/lib/dossier', async (orig) => ({ ...(await orig<typeof import('../src/lib/dossier')>()), usToday: () => '2026-11-04' }))
const { CompanyMentions } = await import('../src/components/company/CompanyMentions')

let search = ''
function Spy() { search = useLocation().search; return null }
const renderAt = (q: string) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[`/us/NVDA${q}`]}>
  <CompanyMentions company="NVDA" market="us" /><Spy /></MemoryRouter></TooltipProvider></QueryClientProvider>)
const rangeAttr = () => document.querySelector('[data-evidence-range]')?.getAttribute('data-evidence-range')
afterEach(() => { cleanup(); calls.length = 0 })

it('defaults to the last week and lists that range', () => {
  renderAt('?tab=evidence')
  expect(rangeAttr()).toBe('2026-10-28~2026-11-04')
  expect(calls.some((c) => c.start === '2026-10-28' && c.end === '2026-11-04')).toBe(true)
  expect(screen.getByRole('button', { name: '기간 요약 만들기' })).toBeTruthy()
})

it('reads legacy ?day= as a one-day range and a bar click sets from/to', () => {
  renderAt('?tab=evidence&day=2026-10-30')
  expect(rangeAttr()).toBe('2026-10-30~2026-10-30')
  fireEvent.click(screen.getByRole('button', { name: '10/20 2건' }))
  expect(search).toContain('from=2026-10-20')
  expect(search).toContain('to=2026-10-20')
  expect(search).not.toContain('day=')
})

it('preset 2주 sets the range ending today', () => {
  renderAt('?tab=evidence')
  fireEvent.click(screen.getByRole('radio', { name: '2주' }))
  expect(search).toContain('from=2026-10-21')
  expect(search).toContain('to=2026-11-04')
})
