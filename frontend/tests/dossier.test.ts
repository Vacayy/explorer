import { describe, expect, it } from 'vitest'
import { disclosureTag, lastClose, pickedDay, quarterCount, rangePos, upside, usConsensus, usTabOf, usTabPath } from '@/lib/dossier'
import type { StockPriceItem } from '@/types'

const bar = (trade_date: string, close: number | null): StockPriceItem => ({ trade_date, open: close, high: close, low: close, close, volume: 1, market_cap: null })

describe('도시에 머리 가격 — 차트와 같은 저장 시세의 마지막 종가', () => {
  it('마지막 종가·전일 대비·기준일, 빈 종가 봉은 건너뛴다', () => {
    const last = lastClose([bar('2026-10-31', 1_480_000), bar('2026-11-03', 1_397_000), bar('2026-11-04', null)])
    expect(last).toEqual({ close: 1_397_000, date: '2026-11-03', changePct: expect.closeTo(-5.608, 2) })
  })
  it('봉이 하나면 변화율 없음, 없으면 null', () => {
    expect(lastClose([bar('2026-11-03', 10)])?.changePct).toBeNull()
    expect(lastClose([])).toBeNull()
    expect(lastClose(undefined)).toBeNull()
  })
  it('목표가 여력', () => {
    expect(upside(150, 100)).toBe(50)
    expect(upside(null, 100)).toBeNull()
    expect(upside(150, null)).toBeNull()
  })
})

describe('국내 기업활동 최근 14일 칸 — 주주환원·실적·지분 공시만', () => {
  it.each([
    ['자기주식취득결정', '주주환원'],
    ['현금ㆍ현물배당결정', '주주환원'],
    ['[기재정정]주식소각결정', '주주환원'],
    ['연결재무제표기준영업(잠정)실적(공정공시)', '실적'],
    ['매출액또는손익구조30%(대규모법인은15%)이상변동', '실적'],
    ['분기보고서 (2026.09)', '실적'],
    ['주식등의대량보유상황보고서(일반)', '지분'],
    ['임원ㆍ주요주주특정증권등소유상황보고서', '지분'],
  ])('%s → %s', (name, tag) => expect(disclosureTag(name)).toBe(tag))
  it('그 밖의 공시는 뺀다', () => {
    expect(disclosureTag('기업설명회(IR)개최')).toBeNull()
    expect(disclosureTag(null)).toBeNull()
  })
})

describe('미국 도시에 탭 — ?tab= 이 유일한 상태', () => {
  it('옛 analysis는 투자 렌즈로, 모르는 값은 개요로', () => {
    expect(usTabOf('?tab=analysis')).toBe('lens')
    expect(usTabOf('?tab=evidence&source=blog')).toBe('evidence')
    expect(usTabOf('?tab=nope')).toBe('overview')
    expect(usTabOf('')).toBe('overview')
  })
  it('개요는 쿼리 없이', () => {
    expect(usTabPath('NVDA', 'overview')).toBe('/us/NVDA')
    expect(usTabPath('NVDA', 'lens')).toBe('/us/NVDA?tab=lens')
  })
})

describe('URL 값 정리', () => {
  it('분기 표시 구간은 4·8·12, 기본 8', () => {
    expect(quarterCount('4')).toBe(4)
    expect(quarterCount('12')).toBe(12)
    expect(quarterCount(null)).toBe(8)
    expect(quarterCount('99')).toBe(8)
  })
  it('언급 흐름에서 고른 날', () => {
    expect(pickedDay('2026-11-03')).toBe('2026-11-03')
    expect(pickedDay('2026-13-40')).toBeNull()
    expect(pickedDay('11/03')).toBeNull()
    expect(pickedDay(null)).toBeNull()
  })
})

describe('미국 컨센서스(yfinance 추정치 스냅샷)', () => {
  const est = {
    revisions: { '0y': { up30: 2, down30: 0 }, '+1y': { up30: 7, down30: 1 } },
    eps_trend_1y: { current: 15.91, d90: 12.81 },
    earnings_1y: { avg: 15.9, growth: 0.709, analysts: 52 },
    price_targets: { current: 202, high: 515, low: 180, mean: 328.95, median: 315 },
  }
  it('필요한 값만 꺼내고 성장률은 %로', () => {
    const c = usConsensus(est)
    expect(c.epsNext).toBe(15.91)
    expect(c.eps90dAgo).toBe(12.81)
    expect(c.growth).toBeCloseTo(70.9, 5)
    expect(c.analysts).toBe(52)
    expect(c.revThis).toEqual({ up: 2, down: 0 })
    expect(c.revNext).toEqual({ up: 7, down: 1 })
    expect(c.targets).toEqual({ low: 180, mean: 328.95, median: 315, high: 515 })
  })
  it('없거나 모양이 틀리면 null', () => {
    const c = usConsensus({ price_targets: { low: 'x' }, revisions: [] })
    expect(c).toEqual({ epsNext: null, eps90dAgo: null, growth: null, analysts: null, revThis: null, revNext: null, targets: null })
    expect(usConsensus(undefined).targets).toBeNull()
  })
  it('목표가 막대 위치는 0~100%로 묶는다', () => {
    expect(rangePos(180, 180, 515)).toBe(0)
    expect(rangePos(515, 180, 515)).toBe(100)
    expect(rangePos(100, 180, 515)).toBe(0)
    expect(rangePos(5, 5, 5)).toBe(50)
  })
})
