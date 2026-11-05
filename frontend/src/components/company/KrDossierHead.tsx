import { useCompany } from '@/hooks/useCompanySearch'
import { useCompanyPrices } from '@/hooks/useCompanyPrices'
import { useKpi } from '@/hooks/useKpi'
import { WatchButton } from '@/components/follow/WatchButton'
import SaveButton from '@/components/shared/SaveButton'
import { DossierHead, MetricStrip } from '@/components/company/DossierHead'
import { lastClose, upside } from '@/lib/dossier'
import { formatKrw, formatPercent, formatRatio, formatStockPrice } from '@/utils/format'

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
      {metrics && <KrMetrics stockCode={stockCode} price={last?.close ?? null} />}
    </div>
  )
}

function KrMetrics({ stockCode, price }: { stockCode: string; price: number | null }) {
  const kpi = useKpi(stockCode)
  const k = kpi.data
  const room = upside(k?.target_price_consensus, price)
  return (
    <MetricStrip loading={kpi.isPending} items={[
      { label: '시가총액', value: formatKrw(k?.market_cap) },
      { label: 'PER · Fwd', value: `${k?.per == null ? '-' : k.per.toFixed(1)} · ${times(k?.fwd_per, 1)}` },
      { label: 'PBR', value: times(k?.pbr, 2) },
      { label: '영업이익률', value: formatRatio(k?.op_margin) },
      { label: 'ROE', value: formatRatio(k?.roe) },
      { label: '목표가 컨센서스', value: k?.target_price_consensus ? formatStockPrice(k.target_price_consensus, 'kr') : '-',
        sub: room != null ? <span className={room >= 0 ? 'text-up' : 'text-down'}>{formatPercent(room)} 여력</span> : undefined },
    ]} />
  )
}
