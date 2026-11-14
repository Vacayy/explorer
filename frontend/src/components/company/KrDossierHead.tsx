import { useCompany } from '@/hooks/useCompanySearch'
import { useCompanyPrices } from '@/hooks/useCompanyPrices'
import { useKpi } from '@/hooks/useKpi'
import { WatchButton } from '@/components/follow/WatchButton'
import SaveButton from '@/components/shared/SaveButton'
import { DossierHead, MetricStrip, type MetricSource } from '@/components/company/DossierHead'
import { lastClose, upside, type LastClose } from '@/lib/dossier'
import { formatKrw, formatKstSlashDate, formatPercent, formatRatio, formatStockPrice } from '@/utils/format'
import type { KpiData } from '@/hooks/useKpi'

const times = (v: number | null | undefined, digits: number) => (v == null ? '-' : `${v.toFixed(digits)}배`)

/** 국내 도시에 머리 — 모든 탭 공통. 핵심 지표 띠는 개요에서만(시안 Dossier-KR) */
export function KrDossierHead({ stockCode, metrics = false }: { stockCode: string; metrics?: boolean }) {
  const { data: company } = useCompany(stockCode)
  const prices = useCompanyPrices(stockCode, 'kr')
  const last = lastClose(prices.data?.items)
  const name = company?.corp_name || stockCode
  return (
    <div className="space-y-3">
      <DossierHead
        market="kr"
        eyebrow={`${stockCode} · ${company?.market || '국내 상장'}${company?.sector ? ` · ${company.sector}` : ''}`}
        name={name}
        last={last}
        loading={prices.isPending}
        actions={<>
          <WatchButton stockCode={stockCode} />
          <SaveButton kind="company" refId={stockCode} url={`/analyze/${stockCode}/summary`} title={name} subtitle={stockCode} />
        </>}
      />
      {metrics && <KrMetrics stockCode={stockCode} last={last} />}
    </div>
  )
}

const CONSENSUS_SOURCE: Record<string, string> = { naver: '네이버 증권(와이즈리포트) 컨센서스', fnguide: 'FnGuide 컨센서스' }
const day = (d?: string | null) => (d ? formatKstSlashDate(d.slice(0, 10)) : undefined)

/** 머리 지표 띠의 ⓘ — 공식·출처·기준일 (routers/kpi.py의 실제 계산 경로와 같게) */
export function krMetricSources(k: KpiData | undefined, last: LastClose | null): Record<string, MetricSource> {
  const dart = k?.latest_year ? `DART ${k.latest_year} 사업보고서(연결 우선, 없으면 별도)` : 'DART 사업보고서'
  const naver = '네이버 증권 종목 지표'
  const cons = (k?.consensus_source && CONSENSUS_SOURCE[k.consensus_source]) || '증권사 컨센서스'
  const analysts = k?.fwd_analyst_count ? ` · 애널리스트 ${k.fwd_analyst_count}명` : ''
  const consAsOf = k?.consensus_fetched_at ? `${formatKstSlashDate(k.consensus_fetched_at, false)} 수집` : undefined
  return {
    market_cap: { formula: '종가 × 상장주식수', source: 'KRX 일별 시세', asOf: k?.price_date ? `${day(k.price_date)} 종가` : undefined },
    per: {
      formula: <>PER: {k?.per_calc ? '시가총액 ÷ 당기순이익' : '주가 ÷ EPS'}<br />Fwd: {k?.fwd_per_calc ? `종가 ÷ ${k?.fwd_fiscal_year ?? '추정'} EPS` : `${k?.fwd_fiscal_year ?? '추정 연도'} 컨센서스 PER`}</>,
      source: <>PER: {k?.per_calc ? dart : naver}<br />Fwd: {cons}{analysts}</>,
      asOf: <>PER: {k?.per_calc ? `${k?.latest_year ?? '-'} 결산` : (day(k?.fund_date) ?? '-')}<br />Fwd: {consAsOf ?? '-'}</>,
    },
    pbr: k?.pbr_calc
      ? { formula: '시가총액 ÷ 자본총계', source: dart, asOf: k?.price_date ? `시가총액 ${day(k.price_date)}` : undefined }
      : { formula: '주가 ÷ BPS', source: naver, asOf: day(k?.fund_date) },
    op_margin: { formula: '영업이익 ÷ 매출액', source: dart, asOf: k?.latest_year ? `${k.latest_year} 연간` : undefined },
    roe: { formula: '당기순이익 ÷ 기말 자본총계', source: dart, asOf: k?.latest_year ? `${k.latest_year} 연간` : undefined },
    target: {
      formula: '증권사 목표가 평균',
      source: `${cons}${analysts}`,
      asOf: consAsOf,
      note: last ? `여력 = (목표가 − 종가) ÷ 종가, ${day(last.date)} 종가 기준` : undefined,
    },
  }
}

function KrMetrics({ stockCode, last }: { stockCode: string; last: LastClose | null }) {
  const kpi = useKpi(stockCode)
  const k = kpi.data
  const room = upside(k?.target_price_consensus, last?.close ?? null)
  const src = krMetricSources(k, last)
  return (
    <MetricStrip loading={kpi.isPending} items={[
      { label: '시가총액', value: formatKrw(k?.market_cap), info: src.market_cap },
      { label: 'PER · Fwd', value: `${k?.per == null ? '-' : k.per.toFixed(1)} · ${times(k?.fwd_per, 1)}`, info: src.per },
      { label: 'PBR', value: times(k?.pbr, 2), info: src.pbr },
      { label: '영업이익률', value: formatRatio(k?.op_margin), info: src.op_margin },
      { label: 'ROE', value: formatRatio(k?.roe), info: src.roe },
      { label: '목표가 컨센서스', value: k?.target_price_consensus ? formatStockPrice(k.target_price_consensus, 'kr') : '-', info: src.target,
        sub: room != null ? <span className={room >= 0 ? 'text-up-ink' : 'text-down-ink'}>{formatPercent(room)} 여력</span> : undefined },
    ]} />
  )
}
