import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { krMetricSources } from '@/components/company/KrDossierHead'
import { usMetricSources } from '@/components/us/UsDossierPage'
import { usConsensus } from '@/lib/dossier'
import type { KpiData } from '@/hooks/useKpi'

const text = (n: ReactNode) => render(<>{n}</>).container.textContent

const kpi = (over: Partial<KpiData>): KpiData => ({
  stock_code: '005930', latest_year: 2025, close: 1, price_change_pct: null, price_date: '2026-11-06',
  market_cap: 1, per: 10, pbr: 1, fund_date: '2026-11-06', per_calc: false, pbr_calc: false,
  op_margin: null, op_margin_change: null, roe: null, roe_change: null, revenue: null, revenue_growth: null,
  op_profit: null, op_profit_growth: null, net_income: null, fwd_per: 5, fwd_per_calc: false, fwd_fiscal_year: '2026E',
  fwd_eps: null, fwd_analyst_count: 24, target_price_consensus: 1, consensus_source: 'naver', consensus_fetched_at: '2026-07-30 07:00:04',
  ...over,
})

describe('도시에 지표 ⓘ — 서버가 실제로 쓴 계산 경로를 보인다', () => {
  it('국내 PER·PBR 저장값이면 네이버·기준일, 자체 계산이면 DART 사업보고서', () => {
    const stored = krMetricSources(kpi({}), null)
    expect(text(stored.per.source)).toContain('네이버 증권 종목 지표')
    expect(text(stored.per.asOf)).toContain('11/06')
    expect(stored.pbr.formula).toBe('주가 ÷ BPS')

    const calc = krMetricSources(kpi({ per_calc: true, pbr_calc: true }), null)
    expect(text(calc.per.formula)).toContain('시가총액 ÷ 당기순이익')
    expect(text(calc.per.source)).toContain('DART 2025 사업보고서')
    expect(calc.pbr.formula).toBe('시가총액 ÷ 자본총계')
  })

  it('국내 목표가는 컨센서스 출처·애널리스트 수·수집일, 여력 기준 종가', () => {
    const s = krMetricSources(kpi({}), { close: 1, date: '2026-11-06', changePct: null })
    expect(s.target.source).toBe('네이버 증권(와이즈리포트) 컨센서스 · 애널리스트 24명')
    expect(s.target.asOf).toBe('07/30 수집')
    expect(s.target.note).toContain('11/06 종가 기준')
  })

  it('미국 PER 공식에 실제 주가·EPS를 넣는다', () => {
    const f = { price: 160.38, market_cap: 1, fwd_pe: 63.3, trailing_pe: 112.9, fwd_eps: 2.535, trailing_eps: 1.42,
      revenue: null, net_income: null, ocf: null, fcf: null, capex: null, earnings_quality: null,
      estimates: { price_targets: { low: 80, mean: 222.25, median: 235, high: 273 } } }
    const s = usMetricSources(f, usConsensus(f.estimates), '2026-11-08 04:28:38', null)
    expect(s.fwd_pe.formula).toBe('$160.38 ÷ 다음 회계연도 추정 EPS $2.54')
    expect(s.trailing_pe.formula).toBe('$160.38 ÷ 최근 12개월 EPS $1.42')
    expect(s.target_mean.formula).toContain('중앙값 $235.00')
    expect(s.market_cap.asOf).toBe('11/08 13:28 수집')
  })
})
