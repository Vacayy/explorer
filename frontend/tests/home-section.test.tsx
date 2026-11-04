import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'

vi.mock('@/components/widgets/registry', () => ({
  WIDGET_BY_ID: {
    ok: { id: 'ok', title: '정상 블록', description: '설명', detailPath: '/home/us', useMeta: () => ({ asOf: '11/04' }), Body: () => <p>정상 본문</p> },
    broken: { id: 'broken', title: '깨진 블록', description: '설명', detailPath: '/home', useMeta: () => ({ asOf: null }), Body: () => { throw new Error('boom') } },
  },
}))
const { HomeSection } = await import('../src/components/home/HomeSection')

afterEach(() => { cleanup(); vi.restoreAllMocks() })

function renderAt(path: string, ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></TooltipProvider></QueryClientProvider>)
}

it('keeps the header and the other blocks when one block body fails (block-level error)', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  renderAt('/home', <><HomeSection widget="broken" /><HomeSection widget="ok" /></>)
  expect(screen.getByRole('heading', { name: '깨진 블록' })).toBeTruthy()
  expect(screen.getByRole('alert').textContent).toContain('다시 시도')
  expect(screen.getByText('정상 본문')).toBeTruthy()
  expect(screen.getByText('11/04')).toBeTruthy()
})

it('links to the full view unless it is the current screen', () => {
  renderAt('/home', <><HomeSection widget="ok" link={{ to: '/home/us', label: '미국 시장' }} /><HomeSection widget="broken" title="머리만" link={null} /></>)
  expect(screen.getByRole('link', { name: '미국 시장 ›' }).getAttribute('href')).toBe('/home/us')
  cleanup()
  renderAt('/home/us', <HomeSection widget="ok" />)
  expect(screen.queryByRole('link')).toBeNull()
})
