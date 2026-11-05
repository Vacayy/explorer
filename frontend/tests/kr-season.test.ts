import { describe, expect, it } from 'vitest'
import { filterAnnouncements, filterCounts, krCalendarBars, krPeak, periodicReportName, reactionExtremes } from '@/lib/krSeason'
import { currentSeasonKey } from '@/lib/seasonBoard'
import type { KrAnnouncement } from '@/types'

const ann = (o: Partial<KrAnnouncement> & { corp_code: string }): KrAnnouncement => ({
  corp_name: o.corp_code, stock_code: o.corp_code, rcept_dt: '2026-10-28', rcp_no: 'r', kind: 'prelim', basis: '연결', group: '금융', market_cap: 2e12,
  r1: null, x1: null, r1_state: 'final', r5: null, x5: null, r5_state: 'pending', figures: null, ...o,
})

describe('국내 실적 시즌 캘린더', () => {
  it('시즌 시작~분기보고서 마감의 평일마다 막대, 주말 공시는 넣는다', () => {
    const bars = krCalendarBars({ season: { key: '2026Q3', label: '', start: '2026-10-30', is_current: true }, deadline: '2026-11-03',
      calendar: [{ date: '2026-10-30', total: 4, quarterly: 0 }, { date: '2026-10-31', total: 1, quarterly: 0 }] })
    expect(bars.map(b => `${b.date}:${b.total}`)).toEqual(['2026-10-30:4', '2026-10-31:1', '2026-11-02:0', '2026-11-03:0'])
  })
  it('마감 뒤 공시가 있으면 그날까지 늘린다', () => {
    const bars = krCalendarBars({ season: { key: '2026Q3', label: '', start: '2026-11-13', is_current: true }, deadline: '2026-11-16',
      calendar: [{ date: '2026-11-17', total: 2, quarterly: 0 }] })
    expect(bars.map(b => b.date)).toEqual(['2026-11-13', '2026-11-16', '2026-11-17'])
  })
  it('하루 최다 공시일', () => {
    expect(krPeak([{ date: 'a', total: 3, quarterly: 0 }, { date: 'b', total: 9, quarterly: 0 }, { date: 'c', total: 9, quarterly: 0 }])?.date).toBe('b')
    expect(krPeak([])).toBeNull()
  })
  it('분기보고서만 낸 회사는 따로 세고, 그것만 있는 주말도 막대로 넣는다(D-305)', () => {
    const bars = krCalendarBars({ season: { key: '2026Q3', label: '', start: '2026-10-30', is_current: true }, deadline: '2026-11-02',
      calendar: [{ date: '2026-10-30', total: 4, quarterly: 2 }, { date: '2026-11-01', total: 0, quarterly: 1 }] })
    expect(bars.map(b => `${b.date}:${b.total}+${b.quarterly}`)).toEqual(['2026-10-30:4+2', '2026-11-01:0+1', '2026-11-02:0+0'])
    expect(krPeak([{ date: 'a', total: 3, quarterly: 9 }, { date: 'b', total: 4, quarterly: 0 }])?.date).toBe('b')   // 최다일은 잠정실적 기준
  })
  it('시즌 결산에 맞는 정기보고서 이름', () => {
    expect(['2026Q1', '2026Q2', '2026Q3', '2026Q4'].map(periodicReportName)).toEqual(['분기보고서', '반기보고서', '분기보고서', '사업보고서'])
  })
})

describe('반응이 좋았던·나빴던 발표', () => {
  it('시총 1조 이상만, 업종 대비 순, 업종 대비 없는 발표는 뺀다', () => {
    const anns = [ann({ corp_code: 'A', x1: 5 }), ann({ corp_code: 'B', x1: 12 }), ann({ corp_code: 'C', x1: 30, market_cap: 5e11 }),
      ann({ corp_code: 'D', x1: -8 }), ann({ corp_code: 'E', x1: -2 }), ann({ corp_code: 'F', x1: null, r1: 9 })]
    const { good, bad } = reactionExtremes(anns)
    expect(good.map(a => a.corp_code)).toEqual(['B', 'A'])
    expect(bad.map(a => a.corp_code)).toEqual(['D', 'E'])
  })
  it('분기보고서만 낸 회사도 반응 목록에 들어간다(D-305)', () => {
    const { good } = reactionExtremes([ann({ corp_code: 'Q', kind: 'quarterly', basis: null, x1: 7 }), ann({ corp_code: 'P', x1: 3 })])
    expect(good.map(a => `${a.corp_code}:${a.kind}`)).toEqual(['Q:quarterly', 'P:prelim'])
  })
})

describe('최근 발표 표 필터', () => {
  const anns = [ann({ corp_code: 'A', stock_code: '000001' }), ann({ corp_code: 'B', stock_code: '000002', market_cap: 1e11, rcept_dt: '2026-10-29' }), ann({ corp_code: 'C', stock_code: null })]
  const mine = new Set(['000002'])
  it('전체·시총 1조+·내 종목 수', () => {
    expect(filterCounts(anns, mine)).toEqual({ all: 3, big: 2, mine: 1 })
  })
  it('캘린더에서 고른 날로 좁힌다', () => {
    expect(filterAnnouncements(anns, 'all', mine, '2026-10-29').map(a => a.corp_code)).toEqual(['B'])
    expect(filterCounts(anns, mine, '2026-10-28')).toEqual({ all: 2, big: 2, mine: 0 })
  })
})

describe('지금 실적 시즌 키', () => {
  it('10~12월은 3분기, 1~3월은 지난해 4분기', () => {
    expect(currentSeasonKey('2026-11-05')).toBe('2026Q3')
    expect(currentSeasonKey('2027-02-01')).toBe('2026Q4')
    expect(currentSeasonKey('2026-07-01')).toBe('2026Q2')
  })
})
