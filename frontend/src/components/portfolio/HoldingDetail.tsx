import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import api from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { DetailLink } from '@/components/shared/DetailNavigation'
import { ErrorState } from '@/components/shared/ErrorState'
import CandlestickChart from '@/components/charts/CandlestickChart'
import { TechnicalScan, scanToChart, useTechnicalScan } from '@/components/company/TechnicalScan'
import { sourceLabels, type EvidenceItem } from '@/components/company/CompanyEvidence'
import { formatNumber } from '@/utils/format'
import type { PortfolioHolding, StockPriceItem } from '@/types'
import { FlowCard } from '@/components/portfolio/FlowCard'
import { ThesisCard } from '@/components/portfolio/ThesisCard'

/** 보유 종목 한 개: 가격(평단선·편입일 + 기술적 분석 표시) · 공시 · 뉴스/관련 자료. */
export function HoldingDetail({ holding }: { holding: PortfolioHolding }) {
  const { code } = holding
  return <div className="space-y-4">
    <PriceCard holding={holding} />
    <ThesisCard code={code} name={holding.name} />
    <div className="grid gap-4 @3xl/portfolio:grid-cols-3">
      <FlowCard code={code} />
      <EvidenceCard code={code} title="최근 공시" source="disclosure" />
      <EvidenceCard code={code} title="뉴스·관련 자료" source="" />
    </div>
  </div>
}

function PriceCard({ holding }: { holding: PortfolioHolding }) {
  const prices = useQuery({
    queryKey: ['company-prices', holding.code, 'kr'],
    queryFn: async ({ signal }) => (await api.get<{ items: StockPriceItem[] }>('/api/spine/feed/company-prices', { params: { company: holding.code, market: 'kr' }, signal })).data,
    staleTime: 300_000,
  })
  // 기술적 분석은 기본으로 켠다(scan=0이면 닫힘). 상태는 기업 화면과 같은 URL 키를 쓴다.
  const [sp, setSp] = useSearchParams()
  const scanOpen = sp.get('scan') !== '0'
  const within = [1, 3, 5, 10, 20].includes(Number(sp.get('scan_within'))) ? Number(sp.get('scan_within')) : 5
  const onChart = sp.get('scan_chart') !== '0'
  const update = (key: string, value: string | null) => setSp(prev => { const n = new URLSearchParams(prev); if (value == null) n.delete(key); else n.set(key, value); return n }, { replace: true, preventScrollReset: true })
  const scan = useTechnicalScan(holding.code, 'kr', within, scanOpen)
  const scanChart = useMemo(() => scanToChart(scanOpen && onChart ? scan.data : undefined), [scan.data, scanOpen, onChart])
  const rows = (prices.data?.items ?? []).slice(-250)
  const data = rows.flatMap(r => r.open != null && r.high != null && r.low != null && r.close != null
    ? [{ time: r.trade_date, open: r.open, high: r.high, low: r.low, close: r.close }] : [])
  // 편입일 마커는 그날(없으면 직전) 캔들에 단다 — 수집 전 당일 편입도 보이게
  const entry = [...rows].reverse().find(r => r.trade_date <= holding.entry_date)?.trade_date
  return <Card>
    <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
      <CardTitle>{holding.name} <span className="text-caption font-normal text-muted-foreground">평단 {formatNumber(holding.avg_price)}원 · {holding.entry_date} 편입</span></CardTitle>
      <DetailLink to={`/analyze/${holding.code}/summary`} className="text-sm text-primary hover:underline">기업 화면 →</DetailLink>
    </CardHeader>
    <CardContent>
      {prices.isPending ? <Skeleton className="h-[320px] w-full" />
        : prices.isError ? <ErrorState onRetry={() => void prices.refetch()} />
        : !data.length ? <p className="py-10 text-center text-sm text-muted-foreground">저장된 시세가 없습니다.</p>
        : (() => {
          const chart = <CandlestickChart key={holding.code} data={data} height={320} formatValue={v => formatNumber(Math.round(v))}
            markers={[...(entry ? [{ time: entry, direction: 'up' as const, text: '편입' }] : []), ...scanChart.markers]}
            overlays={[{ id: 'avg', title: '평단', token: '--chart-warning', dashed: true, data: data.map(d => ({ time: d.time, value: holding.avg_price })) }, ...scanChart.overlays]}
            initialRange={data.length > 120 ? { from: data[data.length - 120].time, to: data[data.length - 1].time } : null} />
          return scanOpen
            ? <TechnicalScan key={holding.code} chart={chart} code={holding.code} market="kr" within={within} onWithin={v => update('scan_within', String(v))}
                onChart={onChart} onToggleChart={v => update('scan_chart', v ? null : '0')} onClose={() => update('scan', '0')} />
            : <div className="space-y-2">{chart}<Button variant="outline" size="sm" onClick={() => update('scan', null)}><Activity aria-hidden="true" />기술적 분석</Button></div>
        })()}
    </CardContent>
  </Card>
}

function EvidenceCard({ code, title, source }: { code: string; title: string; source: '' | 'disclosure' }) {
  const feed = useQuery({
    queryKey: ['company-evidence', { company: code, market: 'kr', source, size: source ? 5 : 15 }],
    queryFn: async ({ signal }) => (await api.get<{ items: EvidenceItem[] }>('/api/spine/feed/company-evidence', { params: { company: code, market: 'kr', source, size: source ? 5 : 15 }, signal })).data,
    staleTime: 60_000,
  })
  // '뉴스·관련 자료'는 공시를 뺀 최신 5건(뉴스만으로는 비는 종목이 많다)
  const items = (feed.data?.items ?? []).filter(i => source || i.source_type !== 'disclosure').slice(0, 5)
  return <Card>
    <CardHeader className="flex-row items-center justify-between"><CardTitle>{title}</CardTitle>
      <DetailLink to={`/analyze/${code}/mentions${source ? '?source=disclosure' : ''}`} className="text-sm text-primary hover:underline">전체 →</DetailLink></CardHeader>
    <CardContent>
      {feed.isPending ? <Skeleton className="h-32 w-full" />
        : feed.isError ? <Button variant="outline" size="sm" onClick={() => void feed.refetch()}>다시 불러오기</Button>
        : !items.length ? <p className="text-sm text-muted-foreground">확보된 자료가 없습니다.</p>
        : <ul className="divide-y">{items.map(item => {
            const label = item.title?.trim() || '제목 없는 자료'
            return <li key={item.id} className="py-2">
              <p className="text-caption text-muted-foreground">{item.local_date} · {sourceLabels[item.source_type] || item.source_type}{item.publisher ? ` · ${item.publisher}` : ''}</p>
              {item.doc_id ? <DetailLink to={`/doc/${item.doc_id}`} className="line-clamp-2 text-sm font-medium hover:underline">{label}</DetailLink>
                : /^https?:\/\//i.test(item.url) ? <a href={item.url} target="_blank" rel="noopener noreferrer" className="line-clamp-2 text-sm font-medium hover:underline">{label} ↗</a>
                : <p className="line-clamp-2 text-sm font-medium">{label}</p>}
            </li>
          })}</ul>}
    </CardContent>
  </Card>
}
