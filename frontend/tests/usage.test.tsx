import { act, render } from '@testing-library/react'
import { MemoryRouter, useNavigate, type NavigateFunction } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/usage', async (orig) => ({ ...(await orig<typeof import('@/lib/usage')>()), track: vi.fn(), flushUsage: vi.fn() }))

import { inPageEvents, isAutomated, placeOf, screenOf, track } from '@/lib/usage'
import { IDLE_CAP_MS, UsageTracker } from '@/components/shared/UsageTracker'

const calls = () => vi.mocked(track).mock.calls.map(([type, name, o]) => ({ type, name, ...o }))

describe('screenOf — 화면 이름은 패턴, 값은 entity', () => {
  it.each([
    ['/industry/반도체', '', '/industry/:sector', '반도체'],
    ['/industry/%EB%B0%98%EB%8F%84%EC%B2%B4', '', '/industry/:sector', '반도체'],
    ['/follow/trade/854232', '', '/follow/trade/:hs', '854232'],
    ['/follow/taiwan/2330', '', '/follow/taiwan/:code', '2330'],
    ['/person/12', '', '/person/:id', '12'],
    ['/analyze/005930/summary', '', '/analyze/:stockCode/summary', '005930'],
    ['/home', '?home_view=feed', '/home?home_view=feed', undefined],
    ['/follow/transcripts', '?t=77', '/follow/transcripts?t', '77'],
    ['/follow/trade', '?hs=854232&trade_sort=surge', '/follow/trade', '854232'],
    ['/follow/taiwan', '?tw=2330', '/follow/taiwan', '2330'],
    ['/industry/반도체', '?tab=peer&group=HBM', '/industry/:sector?tab=peer', '반도체/HBM'],
  ])('%s%s → %s', (path, search, name, entity) => {
    const s = screenOf(path, search)
    expect(s.name).toBe(name)
    expect(s.entity).toBe(entity)
  })

  it('대화상자 쿼리(hs·tw)는 이름에 넣지 않는다 — 같은 화면에서 열면 열람 하나', () => {
    const a = screenOf('/follow/trade', '')
    const b = screenOf('/follow/trade', '?hs=854232')
    expect(inPageEvents(a, b)).toEqual([{ type: 'open', name: 'monitor.open', entity: '854232' }])
    expect(inPageEvents(b, a)).toEqual([])   // 닫기는 남기지 않는다
  })

  it('경로 값이나 화면 쿼리가 바뀌면 새 화면', () => {
    expect(inPageEvents(screenOf('/industry/반도체', ''), screenOf('/industry/조선', ''))).toBeNull()
    expect(inPageEvents(screenOf('/follow/transcripts', ''), screenOf('/follow/transcripts', '?view=season'))).toBeNull()
  })

  it('IA 위치 — 대메뉴·탭, 도시에·관리자는 따로', () => {
    expect(placeOf('/industry/반도체', '?tab=peer')).toEqual({ section: 'industry', tab: 'sectors' })
    expect(placeOf('/follow/trade/854232')).toEqual({ section: 'industry', tab: 'trade' })
    expect(placeOf('/home', '?home_view=feed')).toEqual({ section: 'feed', tab: 'feed' })
    expect(placeOf('/analyze/005930/valuation')).toEqual({ section: 'dossier', tab: 'financials' })
    expect(placeOf('/us/NVDA')).toEqual({ section: 'dossier', tab: 'us' })
    expect(placeOf('/admin', '?view=observe')).toEqual({ section: 'admin', tab: 'observe' })
  })
})

describe('isAutomated — 자동화 브라우저는 기록하지 않는다', () => {
  const store = (v: string | null) => ({ getItem: () => v })
  it('webdriver', () => expect(isAutomated({ webdriver: true, userAgent: 'Mozilla/5.0 Chrome/131' }, store(null))).toBe(true))
  it('headless Chrome UA', () => expect(isAutomated({ webdriver: false, userAgent: 'Mozilla/5.0 HeadlessChrome/131' }, store(null))).toBe(true))
  it('사람 브라우저', () => expect(isAutomated({ webdriver: false, userAgent: 'Mozilla/5.0 Chrome/131' }, store(null))).toBe(false))
  it('점검용 강제 기록 스위치', () => expect(isAutomated({ webdriver: true, userAgent: 'HeadlessChrome' }, store('1'))).toBe(false))
})

let nav: NavigateFunction
function Grab() { nav = useNavigate(); return null }
const mount = (at: string) => render(<MemoryRouter initialEntries={[at]}><UsageTracker /><Grab /></MemoryRouter>)

describe('UsageTracker', () => {
  beforeEach(() => vi.mocked(track).mockClear())
  afterEach(() => vi.useRealTimers())

  it('같은 화면에서 그룹을 24번 바꾸면 방문 1 + 동작 24', () => {
    mount('/industry/반도체?tab=peer&group=G0')
    for (let i = 1; i <= 24; i++) act(() => nav(`/industry/반도체?tab=peer&group=G${i}`))
    const c = calls()
    expect(c.filter(x => x.type === 'view')).toHaveLength(1)
    expect(c.filter(x => x.type === 'leave')).toHaveLength(0)
    const acts = c.filter(x => x.type === 'action')
    expect(acts).toHaveLength(24)
    expect(acts[0]).toMatchObject({ name: 'peer.group', entity: 'G1', ref: '/industry/:sector?tab=peer', section: 'industry', tab: 'sectors' })
  })

  it('대화상자를 열면 open, 상세 페이지로 가면 view·leave', () => {
    mount('/follow/trade')
    act(() => nav('/follow/trade?hs=854232'))
    act(() => nav('/follow/trade/854232'))
    expect(calls().map(x => `${x.type} ${x.name}`)).toEqual([
      'view /follow/trade', 'open monitor.open', 'leave /follow/trade', 'view /follow/trade/:hs'])
  })

  it('입력 없이 5분이 지나면 머문 시간 시계를 멈추고, 입력이 오면 다시 센다', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-06T00:00:00Z'))
    mount('/home')
    act(() => { vi.advanceTimersByTime(30 * 60_000) })   // 30분 자리 비움
    act(() => nav('/feed'))
    const first = calls().find(x => x.type === 'leave')
    expect(first?.dwell_ms).toBe(IDLE_CAP_MS)

    vi.mocked(track).mockClear()
    act(() => { vi.advanceTimersByTime(6 * 60_000) })    // 5분에서 멈춤
    act(() => { window.dispatchEvent(new Event('pointerdown')) })   // 돌아옴
    act(() => { vi.advanceTimersByTime(2 * 60_000) })
    act(() => nav('/home'))
    expect(calls().find(x => x.type === 'leave')?.dwell_ms).toBe(IDLE_CAP_MS + 2 * 60_000)
  })
})
