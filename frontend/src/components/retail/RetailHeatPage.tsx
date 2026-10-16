import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import MultiLineChart from '@/components/charts/MultiLineChart'
import { PageContainer } from '@/components/shared/PageContainer'
import { ErrorState } from '@/components/shared/ErrorState'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ChevronDown } from 'lucide-react'
import { PctileBar, RegimeBadge, metricValue } from '@/components/retail/retailFormat'
import { useChartPalette } from '@/hooks/useChartPalette'
import { useRetailHistory, useRetailSnapshots, useRetailSummary } from '@/hooks/useRetail'
import { formatKrw, formatNumber } from '@/utils/format'
import type { RetailMetric, RetailPoint, RetailSnapshot } from '@/types'

const RANGES = [{ v: '365', l: '1년' }, { v: '1095', l: '3년' }, { v: '1825', l: '5년' }, { v: '10000', l: '전체' }]
const SNAP_KEYS = ['credit_growth', 'deposit_growth', 'value_growth', 'leverage', 'turnover', 'indiv_share']

/** 개인 투자 열기(D-231, docs/specs/retail-heat.md) — 국면·지표·추이·과열 구간 스냅샷·도움말. 기간은 URL `retail_range`. */
export default function RetailHeatPage() {
  const [params, setParams] = useSearchParams()
  const range = RANGES.some(r => r.v === params.get('retail_range')) ? params.get('retail_range')! : '1825'
  const summary = useRetailSummary()
  const history = useRetailHistory(Number(range))
  const snapshots = useRetailSnapshots()

  if (summary.isPending) return <PageContainer><Skeleton className="h-40 w-full rounded-xl" /><Skeleton className="h-96 w-full rounded-xl" /></PageContainer>
  if (summary.isError) return <PageContainer><ErrorState message="개인 투자 열기를 불러오지 못했습니다." onRetry={() => void summary.refetch()} /></PageContainer>
  const s = summary.data

  return <PageContainer>
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-xl font-bold">개인 투자 열기</h2>
      <span className="text-caption text-muted-foreground">금융투자협회·한국거래소 일별 통계{s.as_of ? ` · ${s.as_of} 기준` : ''}</span>
    </div>
    {!s.regime ? <Card><CardContent className="space-y-2 py-10 text-center"><p className="font-medium">아직 수집된 자료가 없습니다</p>
        <p className="text-sm text-muted-foreground">평일 18:30에 받습니다. 지금 받으려면 scripts/collect_retail.py를 실행하세요(첫 수집은 1999년부터라 몇 분 걸립니다).</p></CardContent></Card>
      : <>
        <Card>
          <CardHeader className="space-y-2">
            <div className="flex flex-wrap items-center gap-3"><CardTitle>지금 국면</CardTitle><RegimeBadge regime={s.regime} className="text-sm" /></div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">{s.regime.reasons.map(r => <li key={r}>{r}</li>)}</ul>
            <p className="text-caption text-muted-foreground">규칙으로 판정한 관측 결과이지 매매 신호가 아닙니다. 판정 규칙은 아래 도움말에 있습니다.</p>
            {(!s.krx_configured || !s.accounts_available) && <p className="text-caption text-hypothesis">
              {!s.krx_configured && '개인 거래 비중·순매수·ETF 선호도는 한국거래소 계정(.env KRX_ID·KRX_PW)을 설정하면 채워집니다. '}
              {!s.accounts_available && '주식거래활동계좌는 아직 수집 경로가 없어 국면 판정에서 빠집니다.'}</p>}
          </CardHeader>
          <CardContent><MetricTable metrics={s.metrics} /></CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
            <div className="space-y-1"><CardTitle>추이</CardTitle><CardDescription>증가율 백분위(0~100)는 그날 이전 5년과 비교한 값입니다.</CardDescription></div>
            <ToggleGroup type="single" value={range} variant="outline" size="sm" aria-label="기간"
              onValueChange={v => { if (v) setParams(prev => { const n = new URLSearchParams(prev); n.set('retail_range', v); return n }, { replace: true }) }}>
              {RANGES.map(r => <ToggleGroupItem key={r.v} value={r.v} className="px-3">{r.l}</ToggleGroupItem>)}</ToggleGroup>
          </CardHeader>
          <CardContent>{history.isPending ? <Skeleton className="h-[520px] w-full" />
            : history.isError ? <ErrorState message="추이를 불러오지 못했습니다." onRetry={() => void history.refetch()} />
            : <TrendCharts points={history.data.points} />}</CardContent>
        </Card>

        <Card>
          <CardHeader className="space-y-1"><CardTitle>과열 구간 스냅샷</CardTitle>
            <CardDescription>각 구간 안에서 신용융자 증가율 백분위가 가장 높았던 날의 모습입니다. 오늘과 나란히 비교하세요.</CardDescription></CardHeader>
          <CardContent>{snapshots.isPending ? <Skeleton className="h-48 w-full" />
            : snapshots.isError ? <ErrorState message="스냅샷을 불러오지 못했습니다." onRetry={() => void snapshots.refetch()} />
            : <SnapshotTable snapshots={snapshots.data} today={{ date: s.as_of!, metrics: s.metrics, regime: s.regime, levels: s.levels }} />}</CardContent>
        </Card>
      </>}
    <Help />
  </PageContainer>
}

function MetricTable({ metrics }: { metrics: RetailMetric[] }) {
  return <div className="overflow-x-auto"><Table>
    <TableHeader><TableRow><TableHead>지표</TableHead><TableHead className="text-right">값</TableHead><TableHead>과거 5년 백분위</TableHead><TableHead className="text-right">20일 전 대비</TableHead></TableRow></TableHeader>
    <TableBody>{metrics.map(m => <TableRow key={m.key} className={m.value == null ? 'text-muted-foreground' : ''}>
      <TableCell className="whitespace-nowrap">{m.label}</TableCell>
      <TableCell className="text-right tabular-nums">{metricValue(m)}</TableCell>
      <TableCell><PctileBar value={m.pctile} /></TableCell>
      <TableCell className="text-right tabular-nums text-muted-foreground">{m.pctile_change == null ? '-' : `${m.pctile_change > 0 ? '+' : ''}${formatNumber(Math.round(m.pctile_change))}`}</TableCell>
    </TableRow>)}</TableBody>
  </Table></div>
}

function TrendCharts({ points }: { points: RetailPoint[] }) {
  const palette = useChartPalette(3)
  const data = useMemo(() => points.map(p => ({ ...p, time: p.date,
    credit_jo: p.credit_total == null ? null : Number(p.credit_total) / 1e12,
    deposits_jo: p.deposits == null ? null : Number(p.deposits) / 1e12 })), [points])
  if (!points.length) return <p className="py-10 text-center text-sm text-muted-foreground">이 기간의 자료가 없습니다.</p>
  return <div className="space-y-6">
    <section aria-label="증가율 백분위"><p className="mb-1 text-sm font-medium">20일 증가율의 5년 백분위</p>
      <MultiLineChart data={data} height={240} formatValue={v => formatNumber(Math.round(v))} lines={[
        { key: 'credit_growth_pct', label: '신용융자', color: palette[0] ?? '#888' },
        { key: 'deposit_growth_pct', label: '예탁금', color: palette[1] ?? '#888' },
        { key: 'value_growth_pct', label: '거래대금', color: palette[2] ?? '#888' }]} /></section>
    <section aria-label="잔고"><p className="mb-1 text-sm font-medium">신용융자 잔고·투자자예탁금(조 원)</p>
      <MultiLineChart data={data} height={220} formatValue={v => `${formatNumber(Math.round(v * 10) / 10)}조`} lines={[
        { key: 'credit_jo', label: '신용융자', color: palette[0] ?? '#888' }, { key: 'deposits_jo', label: '예탁금', color: palette[1] ?? '#888' }]} /></section>
    <section aria-label="KOSPI"><p className="mb-1 text-sm font-medium">KOSPI</p>
      <MultiLineChart data={data} height={180} formatValue={v => formatNumber(Math.round(v))} lines={[{ key: 'kospi_close', label: 'KOSPI', color: palette[2] ?? '#888' }]} /></section>
  </div>
}

function SnapshotTable({ snapshots, today }: { snapshots: RetailSnapshot[]; today: Pick<RetailSnapshot, 'date' | 'metrics' | 'regime' | 'levels'> }) {
  const rows = [...snapshots.map(s => ({ ...s, today: false })), { ...today, episode: 'today', name: '오늘', today: true }]
  const labels = SNAP_KEYS.map(k => today.metrics.find(m => m.key === k)?.label ?? k)
  if (!snapshots.length) return <p className="py-6 text-center text-sm text-muted-foreground">구간 스냅샷이 아직 없습니다. 첫 전체 수집 뒤 계산됩니다.</p>
  return <div className="overflow-x-auto"><Table>
    <TableHeader><TableRow><TableHead>구간</TableHead><TableHead>날짜</TableHead><TableHead>국면</TableHead><TableHead className="text-right">신용융자 잔고</TableHead>
      {labels.map(l => <TableHead key={l} className="text-right">{l}</TableHead>)}</TableRow></TableHeader>
    <TableBody>{rows.map(r => <TableRow key={r.episode} className={r.today ? 'bg-primary/5 font-medium' : ''}>
      <TableCell className="whitespace-nowrap">{r.name}</TableCell>
      <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">{r.date}</TableCell>
      <TableCell><RegimeBadge regime={r.regime} /></TableCell>
      <TableCell className="text-right tabular-nums">{r.levels.credit_total == null ? '-' : formatKrw(r.levels.credit_total)}</TableCell>
      {SNAP_KEYS.map(k => { const m = r.metrics.find(x => x.key === k)
        return <TableCell key={k} className="whitespace-nowrap text-right tabular-nums">{m ? metricValue(m) : '-'}
          {m?.pctile != null && <span className="block text-[10px] text-muted-foreground">백분위 {formatNumber(Math.round(m.pctile))}</span>}</TableCell> })}
    </TableRow>)}</TableBody>
  </Table></div>
}

const DERIVED = [
  ['신용융자 증가율', '최근 20영업일 증가액 / 20영업일 전 잔액', '단기간 빚투가 얼마나 빠르게 증가하는가'],
  ['레버리지 강도', '신용융자 잔액 / KOSPI·KOSDAQ 시가총액', '주식시장 규모 대비 신용융자 수준'],
  ['시장 회전 강도', '최근 20일 거래대금 합계 / 평균 시가총액', '시장 규모 대비 얼마나 활발하게 매매하는가'],
  ['개인 거래 비중', '개인 매수·매도 거래대금 / 전체 매수·매도 거래대금', '전체 시장에서 개인이 차지하는 활동 비중'],
  ['투자 참여 증가율', '최근 활동계좌 수 증가 / 직전 기간 계좌 수', '투자 참여 기반 확대 속도'],
  ['투기성 상품 선호도', '레버리지 ETF 거래대금 / 주식시장 거래대금', '투자자가 고위험 상품을 얼마나 선호하는가'],
]
const PRIORITY = [
  ['핵심', '신용거래융자 잔고', '빚투 규모', '일간'], ['핵심', '투자자예탁금', '증시 대기자금', '일간'], ['핵심', '주식거래활동계좌 수', '시장 참여 기반 확대', '일간 통계'],
  ['핵심', '개인투자자 거래대금·비중', '개인 거래 열기', '일간'], ['핵심', '개인투자자 순매수금액', '실제 매수 방향과 강도', '일간'],
  ['높음', '신용융자 / 시가총액', '시장 규모 대비 레버리지', '일간 계산'], ['높음', '시장 거래대금 / 시가총액', '거래 회전·과열 정도', '일간 계산'],
  ['높음', '레버리지 ETF 거래대금', '고위험 투자 선호', '일간'], ['보조', '은행 신용대출·기타대출 증감', '은행권 차입 확대', '월간'],
  ['보조', '연령별 주식 보유자·대출 현황', '세대별 확산 여부', '연간·비정기'],
]
const REGIME_HELP = [
  ['폭넓은 개인 자금 유입', '참여·예탁금·거래대금이 함께 늘어나는 국면 — 개인 자금이 넓게 들어온다.', '예탁금·거래대금·신용융자 증가율 백분위가 모두 60 이상'],
  ['레버리지 의존 상승', '거래대금보다 신용융자가 빠르게 증가 — 레버리지 의존도가 높아질 수 있다.', '신용융자 증가율 백분위 70 이상, 신용융자 증가율 > 거래대금 증가율, 예탁금 백분위 60 미만'],
  ['회전 과열', '신규 참여는 둔화되지만 거래대금은 급증 — 기존 투자자의 매매 회전이 활발.', '거래대금 증가율 백분위 80 이상, 예탁금(·활동계좌) 증가율 백분위 50 미만'],
  ['레버리지 축소', '주가 하락과 신용융자 급감이 동반 — 반대매매 통계를 함께 확인.', 'KOSPI 20일 −5% 이하, 신용융자 증가율 음수·백분위 15 이하'],
]

function Help() {
  return <Collapsible className="rounded-xl border bg-card"><CollapsibleTrigger asChild><Button variant="ghost" className="min-h-12 w-full justify-between px-5">도움말 — 지표와 국면을 읽는 법<ChevronDown className="size-4" /></Button></CollapsibleTrigger>
    <CollapsibleContent className="space-y-6 px-5 pb-6">
      <p className="text-sm text-muted-foreground">절대 잔액만 보면 시장 규모가 커질수록 과열로 오인할 수 있습니다. 그래서 변화 속도와 시장 규모 대비 비율을 함께 보고, 증가 속도를 과거 5년 분포의 백분위로 읽습니다. 같은 30조 원이라도 20일 사이 1조 원이 늘었는지 5조 원이 늘었는지는 시장에서 전혀 다른 의미입니다.</p>
      <HelpTable head={['파생 지표', '계산 방식', '해석']} rows={DERIVED} />
      <p className="text-caption text-muted-foreground">개인 거래 비중은 매수액과 매도액을 합친 기준으로 일관되게 계산합니다. 레버리지 ETF는 상승 방향 상품과 인버스를 나눠 봅니다. 여기서는 대표 종목(레버리지 2·인버스 3) 거래대금을 주식시장 거래대금으로 나눕니다.</p>
      <HelpTable head={['우선순위', '지표', '측정하는 현상', '갱신 주기']} rows={PRIORITY} />
      <p className="text-sm text-muted-foreground">가장 먼저 볼 지표는 신용융자 잔고, 투자자예탁금, 개인 거래대금, 주식거래활동계좌 수 네 가지입니다. 서로 보완적이기 때문입니다. 신용융자가 늘더라도 거래 참여가 약하면 특정 투자자의 레버리지 증가일 수 있고, 예탁금과 신규 계좌만 늘면 실제 매수보다 대기자금이 쌓이는 국면일 수도 있습니다.</p>
      <HelpTable head={['국면', '의미', '판정 규칙']} rows={REGIME_HELP} />
      <p className="text-caption text-muted-foreground">출처: 금융투자협회(증시자금·신용공여·시장 통계), 한국거래소(투자자별 거래실적·ETF). 판정은 위에서부터 먼저 해당하는 국면입니다.</p>
    </CollapsibleContent></Collapsible>
}

function HelpTable({ head, rows }: { head: string[]; rows: string[][] }) {
  return <div className="overflow-x-auto"><Table><TableHeader><TableRow>{head.map(h => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
    <TableBody>{rows.map(r => <TableRow key={r.join('|')}>{r.map((c, i) => <TableCell key={i} className={i === 0 ? 'whitespace-nowrap font-medium' : 'text-muted-foreground'}>{c}</TableCell>)}</TableRow>)}</TableBody></Table></div>
}
