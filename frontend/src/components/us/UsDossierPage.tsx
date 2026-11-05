import { QueryState } from "@/components/shared/QueryState"
import { Link, useLocation, useParams } from 'react-router-dom'
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { rememberRecentStock } from '@/lib/recentStocks'
import { usDossierQuery, usWorldModelQuery } from '@/api/spine'
import { PageContainer } from '@/components/shared/PageContainer'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { CompanyPriceResearch } from '@/components/company/CompanyPriceResearch'
import { CompanyEvidence } from '@/components/company/CompanyEvidence'
import { CompanyMentions } from '@/components/company/CompanyMentions'
import { CompanyOverviewCard } from '@/components/company/CompanyOverview'
import { DossierHead, MetricStrip } from '@/components/company/DossierHead'
import { InfoTip } from '@/components/shared/InfoTip'
import SaveButton from '@/components/shared/SaveButton'
import type { StockPriceItem, UsDossier } from '@/types'
import { LensView } from '@/components/lens/LensPage'
import { WatchButton } from '@/components/follow/WatchButton'
import { UsPriceCollect } from '@/components/us/UsPriceCollect'
import { UsEarningsCard, UsEarningsHistory } from '@/components/us/UsEarningsCard'
import { useCompanyPrices } from '@/hooks/useCompanyPrices'
import { lastClose, rangePos, upside, usConsensus, usEyebrow, usTabOf } from '@/lib/dossier'
import { cn } from '@/lib/utils'
import { formatPercent, formatRatio, formatStockPrice, formatUsd } from '@/utils/format'

const EMPTY_PRICES: StockPriceItem[] = []

function usd(v?: number | null) {
  if (v == null) return '-'
  return v < 0 ? `-${formatUsd(-v)}` : formatUsd(v)
}
const times = (v?: number | null) => (v == null ? '-' : `${v.toFixed(1)}배`)

/**
 * 미국 종목 도시에 (docs/specs/us-dossier.md · ia-redesign §4.9·§4.13) — 탭은 셸 하위 메뉴(?tab=overview|financials|evidence|lens).
 * 머리 가격은 차트와 같은 저장 시세(us_prices) 마지막 종가로 맞춘다(§8.8). 저장 시세가 없으면 '시세 수집'.
 */
export default function UsDossierPage() {
  const { ticker = '' } = useParams<{ ticker: string }>()
  const { search } = useLocation()
  const tab = usTabOf(search)
  const q = useQuery(usDossierQuery(ticker))
  useEffect(() => { if (q.data?.name) rememberRecentStock({ code: q.data.ticker, name: q.data.name, market: 'us' }) }, [q.data?.ticker, q.data?.name])
  const prices = useCompanyPrices(ticker, 'us')
  const last = lastClose(prices.data?.items)

  return <QueryState query={q} loading={<DossierSkeleton />} isEmpty={() => false}>{d => {
    const f = d.fundamentals
    const price = last?.close ?? f?.price ?? null
    const c = usConsensus(f?.estimates)
    const room = upside(c.targets?.mean, price)
    return (
      <PageContainer>
        <DossierHead market="us" eyebrow={usEyebrow(d)} name={d.name} last={last} loading={prices.isPending}
          actions={<>
            <WatchButton stockCode={d.ticker} />
            <SaveButton kind="company" refId={d.ticker} url={`/us/${d.ticker}`} title={d.name} subtitle={d.ticker} />
            <UsPriceCollect ticker={d.ticker} compact />
          </>} />
        <MetricStrip items={[
          { label: '시가총액', value: usd(f?.market_cap) },
          { label: 'Fwd PER', value: times(f?.fwd_pe) },
          { label: 'Trailing PER', value: times(f?.trailing_pe) },
          { label: '목표가 평균', value: c.targets ? formatStockPrice(c.targets.mean, 'us') : '-',
            sub: room != null ? <span className={room >= 0 ? 'text-up' : 'text-down'}>{formatPercent(room)} 여력</span> : undefined },
          { label: '목표가 범위', value: c.targets ? `${formatStockPrice(c.targets.low, 'us')} – ${formatStockPrice(c.targets.high, 'us')}` : '-' },
        ]} />
        {tab === 'evidence' ? <CompanyMentions key={ticker} company={d.ticker} market="us" />
          : tab === 'financials' ? <UsFinancials d={d} price={price} />
          : tab === 'lens' ? <>
            <LensView code={d.ticker} market="us" />
            <WorldModelSection ticker={d.ticker} name={d.name} />
          </>
          : <>
            <CompanyOverviewCard stockCode={d.ticker} market="us" fallback={<p className="text-muted-foreground">사업 설명을 아직 확보하지 못했습니다.</p>} />
            <CompanyPriceResearch
              key={ticker}
              company={d.ticker}
              market="us"
              prices={prices.data?.items || EMPTY_PRICES}
              loading={prices.isPending}
              error={prices.isError}
              retry={() => void prices.refetch()}
              overview={<div className="space-y-3">
                {typeof d.latest_transcript?.id === 'number' && <UsEarningsCard transcriptId={d.latest_transcript.id} />}
                <CompanyEvidence company={d.ticker} market="us" preview moreTo={`/us/${d.ticker}?tab=evidence`} />
              </div>}
            />
          </>}
      </PageContainer>
    )
  }}</QueryState>
}

function DossierSkeleton() {
  return <div className="space-y-3"><Skeleton className="h-24 w-full" /><Skeleton className="h-20 w-full" /><Skeleton className="h-64 w-full" /></div>
}

/** 실적·사업 탭 — 확보 재무(부분 데이터) · 컨센서스와 목표가 범위 · 실적 발표 이력 */
function UsFinancials({ d, price }: { d: UsDossier; price: number | null }) {
  const f = d.fundamentals
  const c = usConsensus(f?.estimates)
  const margin = f?.revenue && f.net_income != null ? (f.net_income / f.revenue) * 100 : null
  const epsChange = c.epsNext != null && c.eps90dAgo ? ((c.epsNext - c.eps90dAgo) / Math.abs(c.eps90dAgo)) * 100 : null
  const room = upside(c.targets?.mean, price)
  return <>
    <Card className="gap-0 py-0" aria-label="확보된 재무">
      <header className="flex flex-wrap items-center gap-x-2 border-b px-4 py-3">
        <h2 className="text-section font-semibold">확보된 재무</h2>
        <span className="text-caption text-muted-foreground">Yahoo Finance</span>
      </header>
      <div className="space-y-3 p-4">
        {!f ? <p className="text-sm text-muted-foreground">재무 스냅샷을 아직 받지 못했습니다.</p> : <MetricStrip items={[
          { label: '매출', value: usd(f.revenue), sub: '최근 회계연도' },
          { label: '순이익', value: usd(f.net_income), sub: margin != null ? `순이익률 ${formatRatio(margin)}` : undefined },
          { label: '영업현금흐름', value: usd(f.ocf) },
          { label: '잉여현금흐름', value: usd(f.fcf), sub: f.capex != null ? `설비투자 ${usd(Math.abs(f.capex))}` : undefined },
          { label: '이익의 질', value: f.earnings_quality == null ? '-' : `${f.earnings_quality.toFixed(2)}배`, sub: f.earnings_quality == null ? undefined : f.earnings_quality < 1 ? '1배 미만' : '1배 이상' },
        ]} />}
        <div className="flex flex-wrap items-center gap-2 bg-muted/60 px-3 py-2 text-sm">
          <Badge variant="outline" className="border-chart-warning/40 text-chart-warning">부분 데이터</Badge>
          <span>분기 재무·사업부 구성이 아직 없습니다</span>
          <InfoTip label="부분 데이터 설명">미국 재무 저장본에는 분기별 계열·회계기간·사업부 구성이 없어 분기 추이를 만들지 않습니다. 이익의 질은 영업현금흐름 ÷ 순이익입니다.</InfoTip>
          <span className="ml-auto" />
          <Button asChild variant="outline" size="sm"><Link to={`/us/${d.ticker}?tab=evidence&source=transcript`}>컨콜 원문 확인 ›</Link></Button>
        </div>
      </div>
    </Card>
    <Card className="gap-0 py-0" aria-label="컨센서스와 목표가">
      <header className="flex flex-wrap items-center gap-x-2 border-b px-4 py-3">
        <h2 className="text-section font-semibold">컨센서스와 목표가</h2>
        {c.analysts != null && <span className="text-caption text-muted-foreground">애널리스트 {c.analysts}명</span>}
      </header>
      <div className="space-y-4 p-4">
        <MetricStrip items={[
          { label: '내년 EPS 컨센서스', value: c.epsNext == null ? '-' : formatStockPrice(c.epsNext, 'us'),
            sub: c.eps90dAgo != null && epsChange != null ? <>90일 전 {formatStockPrice(c.eps90dAgo, 'us')} → <span className={epsChange >= 0 ? 'text-up' : 'text-down'}>{formatPercent(epsChange)}</span></> : undefined },
          { label: '이익 성장 컨센서스', value: formatPercent(c.growth) },
          { label: '30일 추정 변경 · 올해', value: c.revThis ? `상향 ${c.revThis.up} · 하향 ${c.revThis.down}` : '-' },
          { label: '30일 추정 변경 · 내년', value: c.revNext ? `상향 ${c.revNext.up} · 하향 ${c.revNext.down}` : '-' },
          { label: 'Fwd PER', value: times(f?.fwd_pe), sub: `Trailing ${times(f?.trailing_pe)}` },
        ]} />
        {c.targets ? <section aria-label="증권사 목표가 범위" className="space-y-1">
          <h3 className="text-caption font-medium text-muted-foreground">증권사 목표가 범위</h3>
          <div className="relative mx-2 mt-6 h-2 bg-muted">
            <span className="absolute top-1/2 h-4 w-px -translate-y-1/2 bg-foreground" style={{ left: `${rangePos(c.targets.mean, c.targets.low, c.targets.high)}%` }} />
            <span className="absolute -top-5 -translate-x-1/2 whitespace-nowrap font-mono text-caption tabular-nums" style={{ left: `${rangePos(c.targets.mean, c.targets.low, c.targets.high)}%` }}>평균 {formatStockPrice(c.targets.mean, 'us')}</span>
            {price != null && <span className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground" title={`현재 ${formatStockPrice(price, 'us')}`} style={{ left: `${rangePos(price, c.targets.low, c.targets.high)}%` }} />}
          </div>
          <div className="mx-2 flex justify-between font-mono text-caption tabular-nums text-muted-foreground">
            <span>최저 {formatStockPrice(c.targets.low, 'us')}</span>
            <span>최고 {formatStockPrice(c.targets.high, 'us')}</span>
          </div>
          <p className="text-sm">현재 {price != null ? formatStockPrice(price, 'us') : '-'}{room != null && <> · 평균 목표가까지 <span className={cn('font-mono', room >= 0 ? 'text-up' : 'text-down')}>{formatPercent(room)}</span></>}</p>
        </section> : <p className="text-sm text-muted-foreground">목표가 컨센서스가 없습니다.</p>}
      </div>
    </Card>
    {typeof d.latest_transcript?.id === 'number' ? <UsEarningsHistory transcriptId={d.latest_transcript.id} />
      : <Card><CardContent className="py-3 text-sm text-muted-foreground">받은 실적 발표가 아직 없습니다.</CardContent></Card>}
  </>
}

/** 월드모델 — 이 종목 노드의 인과 위치(엣지) + 걸린 내러티브 + 온톨로지 그래프 딥링크. */
function WorldModelSection({ ticker, name }: { ticker: string; name: string }) {
  const q = useQuery(usWorldModelQuery(ticker))
  const w = q.data
  if (q.isLoading)
    return (
      <Card>
        <CardContent className="py-3">
          <Skeleton className="h-16 w-full rounded-card" />
        </CardContent>
      </Card>
    )
  if (!w || (w.edges.length === 0 && w.narratives.length === 0)) {
    return (
      <Card>
        <CardContent className="py-3">
          <span className="text-sm font-semibold">월드모델 · 인과 위치</span>
          <p className="mt-2 text-sm text-muted-foreground">
            아직 이 종목에 연결된 인과 관계·내러티브가 없습니다.
          </p>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card>
      <CardContent className="py-3 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1 text-sm font-semibold">월드모델 · 인과 위치
            <InfoTip label="월드모델 설명">{name} 노드가 걸린 인과 연결·내러티브입니다. 가치 렌즈의 '구조적 동인·해자'가 여기서 옵니다(가설).</InfoTip>
          </span>
          {w.entity_id != null && (
            <Link
              to={`/knowledge/ontology?focus=${w.entity_id}`}
              className="text-xs text-primary hover:underline"
            >
              온톨로지 그래프에서 보기 →
            </Link>
          )}
        </div>

        {w.edges.length > 0 && (
          <ul className="space-y-1">
            {w.edges.map((e, i) => {
              const dirCls =
                e.direction === 'positive'
                  ? 'text-up'
                  : e.direction === 'negative'
                    ? 'text-down'
                    : 'text-muted-foreground'
              return (
                <li key={i} className="text-xs flex items-baseline gap-1.5">
                  <span className={dirCls}>●</span>
                  <span className="text-muted-foreground">
                    <b className="text-foreground">{e.src}</b>{' '}
                    {e.rel_type === 'CAUSES' ? '→' : '←수혜'}{' '}
                    <b className="text-foreground">{e.dst}</b>
                    {e.mechanism ? ` · ${e.mechanism}` : ''}
                  </span>
                </li>
              )
            })}
          </ul>
        )}

        {w.narratives.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 border-t pt-2">
            <span className="text-[10px] text-muted-foreground shrink-0">
              걸린 내러티브
            </span>
            {w.narratives.map((n) => (
              <Link
                key={n.id}
                to={`/narrative?topic=${encodeURIComponent(n.topic)}`}
                className="text-[11px] rounded-md border px-1.5 py-0.5 hover:border-foreground/30 hover:bg-accent/40"
                title={n.title ?? n.topic}
              >
                {n.topic}
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
