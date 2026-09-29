import { Info } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { RiskTrendChart } from '@/components/charts/RiskTrendChart'
import { useRisk } from '@/hooks/useRisk'
import { formatNumber } from '@/utils/format'
import type { RiskIndicator } from '@/types'

const CREDIT = { hy: 'HY OAS', bbb: 'BBB OAS', aaa: 'AAA OAS', aaa10y: 'Aaa − 10Y', baa10y: 'Baa − 10Y' }
const MACRO_RANGES: Record<string, string> = { '3m': '3개월', '1y': '1년', '3y': '3년', '5y': '5년', '10y': '10년', '20y': '20년', all: '전체' }
const SENTIMENT_RANGES: Record<string, string> = { '1m': '1개월', '3m': '3개월', '1y': '1년' }
const CREDIT_HELP: Record<keyof typeof CREDIT, { role: string; detail: string }> = {
  hy: { role: '취약 차주의 자금조달 스트레스', detail: '투자등급 미만 회사채의 옵션조정 스프레드입니다. 확대는 투자자가 더 큰 신용·유동성 위험 프리미엄을 요구한다는 뜻입니다. 경기와 위험선호 변화에 민감해 동시 경계 조건의 기본 지표로 사용합니다. 부도 확률 자체는 아닙니다.' },
  bbb: { role: '투자등급 하단으로 번지는 신용 부담', detail: '투자등급 중 가장 낮은 BBB 등급 회사채의 옵션조정 스프레드입니다. HY의 불안이 투자등급 기업으로도 확산되는지 비교할 때 유용합니다. 확대만으로 실제 등급 강등을 확정할 수는 없습니다.' },
  aaa: { role: '우량 기업의 신용·유동성 여건', detail: '최상위 AAA 등급 회사채의 옵션조정 스프레드입니다. 우량 차주까지 조달 부담이 커지는지 살펴봅니다. 일반적으로 위험 프리미엄이 낮아 취약 차주 전체의 스트레스를 대표하지는 않습니다.' },
  aaa10y: { role: '우량 회사채의 장기 금리 프리미엄', detail: 'Moody’s Aaa 회사채 수익률에서 미국 10년 국채 금리를 뺀 값입니다. 긴 시계열로 우량 회사채와 국채의 격차를 비교할 수 있습니다. 만기·듀레이션과 옵션 효과가 남아 AAA OAS와 같은 지표로 취급하면 안 됩니다.' },
  baa10y: { role: '투자등급 하단의 장기 신용 사이클', detail: 'Moody’s Baa 회사채 수익률에서 미국 10년 국채 금리를 뺀 값입니다. 투자등급 하단의 조달 부담을 과거 위기 구간과 비교할 때 유용합니다. HY와 대상이 다르고 만기·옵션 효과도 남으므로 HY 또는 BBB OAS의 대체값으로 이어 붙이지 않습니다.' },
}
const ECONOMIC_MEANING = {
  curve: {
    title: '장단기 역전은 왜 경계 신호일까요?',
    summary: '장단기 역전은 시장이 향후 경기 둔화와 금리 인하를 예상하고 있다는 신호일 수 있습니다.',
    paragraphs: [
      { title: '현재의 긴축과 미래의 둔화 기대', text: '10Y − 2Y가 음수이면 2년 금리가 10년 금리보다 높은 역전 상태입니다. 가까운 시기의 금리는 높지만, 이후 경기가 약해져 금리를 내려야 한다는 기대가 장기 금리에 반영될 수 있습니다. 과거 침체에 앞서 자주 나타나 경기 기대의 변화를 살피는 데 활용합니다.' },
      { title: '역전 해소도 방향을 함께 봅니다', text: '2년 금리가 더 빠르게 떨어지며 금리차가 양수로 돌아오는 경우, 경기 회복보다 급격한 금리 인하 기대를 반영할 수 있습니다. 역전 여부뿐 아니라 두 금리의 방향과 신용 스프레드를 함께 봅니다.' },
      { title: '침체의 확정이나 시점 예측은 아닙니다', text: '물가 안정 기대나 장기 채권 보유에 대한 보상인 기간 프리미엄 변화도 금리차를 움직입니다. 역전 자체가 침체를 일으킨다는 뜻은 아니며, 고용·대출 여건 등으로 해석을 확인해야 합니다.' },
    ],
    source: 'Fed 연구 · 수익률곡선의 해석과 한계',
    url: 'https://www.federalreserve.gov/econres/notes/feds-notes/dont-fear-the-yield-curve-reprise-20220325.html',
  },
  credit: {
    title: '금리 하락과 스프레드 확대가 겹치면 왜 위험할까요?',
    summary: '국채 금리가 내려가는데 신용 스프레드가 커지면, 경기 둔화 우려와 기업의 자금조달 부담이 함께 커지는지 경계합니다.',
    paragraphs: [
      { title: '안전자산 선호와 기업 위험의 동시 반영', text: '국채 금리 하락은 금리 인하 기대나 안전자산 수요를 반영할 수 있습니다. 동시에 회사채 스프레드가 확대되면 투자자는 기업의 상환 불안·유동성 위험에 더 큰 보상을 요구하는 것입니다. 두 흐름이 겹치면 경기 둔화와 위험 회피가 함께 진행되는지 살펴볼 이유가 됩니다.' },
      { title: '금리 인하의 효과가 기업에 덜 전달될 수 있습니다', text: '추가 위험 보상이 커지면 국채 금리 하락에 따른 조달비용 개선이 상쇄될 수 있습니다. 자금조달이 어려워지면 기업의 투자·고용과 이익에 부담이 되어 주식 등 위험자산에도 영향을 줍니다. 회사채 금리 자체가 오르는지는 두 변화의 크기에 따라 다릅니다.' },
      { title: '지속성과 확산을 확인합니다', text: '일시적 유동성 불안도 같은 흐름을 만들 수 있어 침체 진입을 단정하지 않습니다. 금리 하락과 스프레드 확대가 지속되는지, HY의 불안이 BBB 등 투자등급으로 번지는지, 고용·대출 지표도 약해지는지 함께 확인합니다.' },
    ],
    source: 'Fed 연구 · 신용 위험 프리미엄과 침체 위험',
    url: 'https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/recession-risk-and-the-excess-bond-premium-20160408.html',
  },
}

function EconomicMeaning({ kind }: { kind: keyof typeof ECONOMIC_MEANING }) {
  const meaning = ECONOMIC_MEANING[kind]
  return <div className="space-y-1 border-t pt-3">
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-auto gap-1.5 px-0 py-1 text-caption" aria-label={`${kind === 'curve' ? '장단기 금리차' : '금리와 신용 위험'} 경제적 의미`}>
          <Info className="size-3.5" aria-hidden="true" />왜 모니터링하나요?
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(420px,calc(100vw-32px))] max-h-[65vh] overflow-y-auto space-y-4">
        <h3 className="text-sm font-semibold">{meaning.title}</h3>
        {meaning.paragraphs.map(paragraph => <div key={paragraph.title}>
          <h4 className="text-sm font-medium">{paragraph.title}</h4>
          <p className="mt-1 text-caption leading-relaxed text-muted-foreground">{paragraph.text}</p>
        </div>)}
        <a href={meaning.url} target="_blank" rel="noreferrer" className="block text-caption text-muted-foreground underline underline-offset-2">{meaning.source}</a>
      </PopoverContent>
    </Popover>
    <p className="text-sm leading-relaxed text-muted-foreground">{meaning.summary}</p>
  </div>
}

function RangeSelect({ value, onChange, label, ranges = MACRO_RANGES }: { value: string; onChange: (value: string) => void; label: string; ranges?: Record<string, string> }) {
  return <Select value={value} onValueChange={onChange}><SelectTrigger className="w-24" aria-label={label}><SelectValue /></SelectTrigger><SelectContent>{Object.entries(ranges).map(([key, text]) => <SelectItem key={key} value={key}>{text}</SelectItem>)}</SelectContent></Select>
}
function CreditHelp({ selected }: { selected: keyof typeof CREDIT }) {
  return <Popover><PopoverTrigger asChild><Button variant="ghost" size="icon" aria-label="신용 위험 지표 설명" title="신용 위험 지표 설명"><Info className="size-4" /></Button></PopoverTrigger><PopoverContent align="end" className="w-[min(400px,calc(100vw-32px))] max-h-[65vh] overflow-y-auto space-y-4">
    <div><h3 className="text-sm font-semibold">신용 위험 지표 읽기</h3><p className="mt-1 text-caption text-muted-foreground">스프레드는 위험을 부담하는 대가입니다. 확대될수록 회사채에 요구하는 추가 보상이 커집니다. 100bp = 1%p.</p></div>
    <p className="text-caption text-muted-foreground">OAS는 FRED에서 최근 3년만 제공합니다. 이전 구간은 비워 둡니다. 더 긴 신용 이력은 Aaa − 10Y / Baa − 10Y를 선택하세요. 경계 판정은 선택한 계열과 무관하게 HY OAS를 사용합니다.</p>
    {Object.entries(CREDIT_HELP).map(([key, help]) => <div key={key} className={key === selected ? 'rounded-lg bg-accent p-3' : ''}><h4 className="text-sm font-medium">{CREDIT[key as keyof typeof CREDIT]} · {help.role}</h4><p className="mt-1 text-caption leading-relaxed text-muted-foreground">{help.detail}</p></div>)}
    <p className="text-caption text-muted-foreground">OAS는 옵션 효과를 조정한 국채 곡선 대비 격차입니다. 10년 국채 금리를 다시 빼지 않습니다. 원천 정의는 각 차트 아래 출처 링크에서 확인할 수 있습니다.</p>
  </PopoverContent></Popover>
}
const QUALITY = { fresh: '관측 확인', stale: '관측 지연', error: '수집 실패 · 저장값', missing: '미수집' }
const number = (n: number | null | undefined) => formatNumber(n == null ? null : Math.round(n * 100) / 100)
const change = (n: number | null | undefined, unit: string) => n == null ? '미평가' : `${n > 0 ? '+' : ''}${number(n)}${unit}`

function Metadata({ item }: { item: RiskIndicator }) {
  return <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">
    <span>{item.as_of ? `${item.as_of} 관측` : '관측일 없음'}</span>
    {item.quality !== 'fresh' && <Badge variant="outline">{QUALITY[item.quality]}</Badge>}
    <a href={item.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{item.source}</a>
    {item.fetched_at && <span title={item.fetched_at}>수집 {new Date(item.fetched_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })} KST</span>}
  </div>
}

export function RiskMonitoring() {
  const query = useRisk()
  const [params, setParams] = useSearchParams()
  const requestedCredit = params.get('risk_credit') ?? 'hy'
  const creditKey = Object.hasOwn(CREDIT, requestedCredit) ? requestedCredit as keyof typeof CREDIT : 'hy'
  const readRange = (key: string, legacy: string, fallback: string, choices: Record<string, string>) => {
    const requested = params.get(key) ?? params.get(legacy) ?? fallback
    return Object.hasOwn(choices, requested) ? requested : fallback
  }
  const curveRange = readRange('risk_curve_range', 'risk_macro_range', '10y', MACRO_RANGES)
  const creditRange = readRange('risk_credit_range', 'risk_macro_range', '10y', MACRO_RANGES)
  const vixRange = readRange('risk_vix_range', 'risk_range', '3m', SENTIMENT_RANGES)
  const fearRange = readRange('risk_fear_range', 'risk_range', '3m', SENTIMENT_RANGES)
  const setParam = (key: string, value: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set(key, value); return next }, { replace: true, preventScrollReset: true })
  const data = query.data
  const items = useMemo(() => Object.fromEntries((data?.items ?? []).map(item => [item.key, item])), [data])
  const cutoffs = useMemo(() => {
    const cutoff = (range: string) => {
      if (range === 'all') return '1962-01-01'
      const d = new Date(`${data?.expected_date ?? '1970-01-01'}T00:00:00Z`)
      if (range.endsWith('m')) d.setUTCMonth(d.getUTCMonth() - Number.parseInt(range))
      else d.setUTCFullYear(d.getUTCFullYear() - Number.parseInt(range))
      return d.toISOString().slice(0, 10)
    }
    return { curve: cutoff(curveRange), credit: cutoff(creditRange), vix: cutoff(vixRange), fear: cutoff(fearRange) }
  }, [data?.expected_date, curveRange, creditRange, vixRange, fearRange])
  const visible = useMemo(() => Object.fromEntries(Object.entries(items).map(([k, item]) => {
    const cutoff = k === 'curve' ? cutoffs.curve : k === 'vix' ? cutoffs.vix : k === 'fear_greed' ? cutoffs.fear : cutoffs.credit
    return [k, item.points.filter(([d]) => d >= cutoff)]
  })), [items, cutoffs])
  const creditDates = useMemo(() => [...new Set([...(visible.us10y ?? []), ...(visible[creditKey] ?? [])].map(([d]) => d))].sort(), [visible, creditKey])
  if (query.isLoading) return <section aria-label="Risk 모니터링 불러오는 중" aria-busy="true" className="space-y-3"><h2 className="text-section font-semibold">Risk 모니터링</h2><div className="grid grid-cols-1 gap-5 @3xl/market:grid-cols-2">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-80 rounded-xl" />)}</div></section>
  if (!data) return <ErrorState message="Risk 모니터링을 불러오지 못했습니다." onRetry={() => void query.refetch()} />
  const curve = items.curve, credit = items[creditKey], vix = items.vix, fear = items.fear_greed
  const coverageTolerance = new Date(`${cutoffs.curve}T00:00:00Z`)
  coverageTolerance.setUTCDate(coverageTolerance.getUTCDate() + 7)
  const curveHistoryShort = curveRange !== 'all' && curve.points.length > 0 && curve.points[0][0] > coverageTolerance.toISOString().slice(0, 10)
  const signal = data.signal
  const alert = ['joint', 'watch', 'credit'].includes(signal.status)
  const refreshFailures = query.snapshot?.results.filter(result => result.status === 'error') ?? []
  return <section aria-labelledby="risk-title" className="space-y-4" data-testid="risk-monitoring">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 id="risk-title" className="text-section font-semibold">Risk 모니터링</h2><p className="text-caption text-muted-foreground">미국 금리·신용·변동성·투자심리 · 일별 저장 관측</p></div>
      <RefreshButton onClick={query.refresh} pending={query.refreshing} title="Risk 데이터 수집 (6시간 캐시)" />
    </div>
    {query.isError && <div role="alert" className="flex items-center gap-2 text-sm text-destructive">조회에 실패해 이전 응답을 표시합니다.<Button variant="outline" size="sm" onClick={() => void query.refetch()}>조회 재시도</Button></div>}
    {(query.refreshError || refreshFailures.length > 0) && <p role="alert" className="text-sm text-destructive">{query.refreshError ? '수집 요청에 실패했습니다. 저장된 관측을 유지합니다.' : `일부 수집 실패: ${refreshFailures.map(r => items[r.key]?.label ?? r.key).join(', ')}. 기존 관측을 유지합니다.`}</p>}
    {query.snapshot?.busy && <p role="status" className="text-sm text-muted-foreground">다른 수집이 진행 중입니다. 잠시 후 조회를 다시 시도해 주세요.<Button variant="ghost" size="sm" onClick={() => void query.refetch()}>조회</Button></p>}
    {data.empty && <p className="rounded-xl border p-4 text-sm text-muted-foreground">아직 Risk 데이터가 없습니다. 오른쪽 갱신 버튼으로 데이터를 수집할 수 있습니다.</p>}
    <div role="status" className={`rounded-xl border px-4 py-3 ${alert ? 'border-hypothesis/30 bg-hypothesis/5' : 'bg-muted/30'}`}>
      <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{signal.label}</Badge><span className="text-sm">{signal.reason}</span><span className="text-caption text-muted-foreground">실험 규칙</span></div>
      <p className="mt-1 text-caption text-muted-foreground">공통 기준일 {signal.as_of ?? '없음'} · 20 공통 관측일: 10Y {change(signal.rate_change_bp, 'bp')} / HY OAS {change(signal.credit_change_bp, 'bp')} · 연속 {number(signal.consecutive)}회</p>
    </div>
    <div className="grid grid-cols-1 gap-5 @3xl/market:grid-cols-2">
      <Card className="min-w-0" data-risk-card="curve"><CardHeader><div className="flex items-center justify-between gap-2"><CardTitle>장단기 금리차</CardTitle><RangeSelect value={curveRange} onChange={value => setParam('risk_curve_range', value)} label="장단기 금리차 기간" /></div><div className="flex items-center justify-between gap-2"><span className="text-2xl font-semibold tabular-nums">{number(curve.value)} <small className="text-sm font-normal">bp</small></span></div><p className="text-caption text-muted-foreground">10Y − 2Y · 20 관측일 {change(curve.change_20, 'bp')}</p></CardHeader><CardContent className="space-y-3">
        {curveHistoryShort && <div role="status" className="rounded-lg bg-muted/40 p-3 text-caption text-muted-foreground">{MACRO_RANGES[curveRange]}을 선택했지만 저장 이력은 {curve.points[0][0]}부터입니다. 확보한 구간만 표시합니다.<Button variant="link" size="sm" className="h-auto px-1 py-0" disabled={query.isFetching} onClick={() => void query.refetch()}>저장 이력 다시 조회</Button></div>}
        <RiskTrendChart points={visible.curve} label="장단기 금리차" unit="bp" zero />
        <p className="text-caption text-muted-foreground">2Y {number(items.us2y.value)}% ({items.us2y.as_of ?? '미수집'}) · 10Y {number(items.us10y.value)}% ({items.us10y.as_of ?? '미수집'})</p>
        <EconomicMeaning kind="curve" /><Metadata item={curve} />
      </CardContent></Card>
      <Card className="min-w-0" data-risk-card="credit"><CardHeader><div className="flex items-center justify-between gap-2"><CardTitle>10년 금리와 신용 위험</CardTitle><RangeSelect value={creditRange} onChange={value => setParam('risk_credit_range', value)} label="신용 차트 기간" /></div><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-2xl font-semibold tabular-nums">{number(credit.value)} <small className="text-sm font-normal">bp</small></span><div className="flex items-center gap-1"><Select value={creditKey} onValueChange={value => setParam('risk_credit', value)}><SelectTrigger className="w-32" aria-label="신용 스프레드 계열"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(CREDIT).map(([key, label]) => <SelectItem key={key} value={key}>{label}</SelectItem>)}</SelectContent></Select><CreditHelp selected={creditKey} /></div></div><p className="text-caption text-muted-foreground">{credit.label} · 20 관측일 {change(credit.change_20, 'bp')}</p></CardHeader><CardContent className="space-y-2">
        <p className="text-caption text-down">10Y · % · {items.us10y.as_of ?? '미수집'}{items.us10y.quality !== 'fresh' ? ` · ${QUALITY[items.us10y.quality]}` : ''}</p><RiskTrendChart points={visible.us10y} dates={creditDates} label="미국 10년 국채 금리" unit="%" height={125} color="--down" />
        <p className="text-caption text-up">{credit.label} · bp</p><RiskTrendChart points={visible[creditKey]} dates={creditDates} label={credit.label} unit="bp" height={125} color="--up" />
        <EconomicMeaning kind="credit" /><Metadata item={credit} />
      </CardContent></Card>
      <Card className="min-w-0" data-risk-card="vix"><CardHeader><div className="flex items-center justify-between gap-2"><CardTitle>VIX</CardTitle><RangeSelect value={vixRange} onChange={value => setParam('risk_vix_range', value)} label="VIX 기간" ranges={SENTIMENT_RANGES} /></div><div><span className="text-2xl font-semibold tabular-nums">{number(vix.value)}</span></div><p className="text-caption text-muted-foreground">5 관측일 {change(vix.change_5, 'pt')} · S&amp;P 500 옵션 기반</p></CardHeader><CardContent className="space-y-3"><RiskTrendChart points={visible.vix} label="VIX" unit="pt" /><p className="text-sm text-muted-foreground">향후 30일의 예상 변동성입니다. 주가 방향이나 침체 여부를 확정하는 지표는 아닙니다.</p><Metadata item={vix} /></CardContent></Card>
      <Card className="min-w-0" data-risk-card="fear"><CardHeader><div className="flex items-center justify-between gap-2"><CardTitle>공포·탐욕</CardTitle><RangeSelect value={fearRange} onChange={value => setParam('risk_fear_range', value)} label="공포·탐욕 기간" ranges={SENTIMENT_RANGES} /></div><div><span className="text-2xl font-semibold tabular-nums">{number(fear.value)} <small className="text-sm font-normal">/ 100</small></span></div><p className="text-caption text-muted-foreground">5 관측일 {change(fear.change_5, 'pt')} · CNN 미국 주식 심리</p></CardHeader><CardContent className="space-y-3"><RiskTrendChart points={visible.fear_greed} label="공포·탐욕" unit="pt" bounded /><p className="text-sm text-muted-foreground">낮을수록 공포, 높을수록 탐욕입니다. VIX·신용 관련 요소와 겹치므로 독립 위험 점수로 합산하지 않습니다.</p><Metadata item={fear} /></CardContent></Card>
    </div>
    <p className="text-caption text-muted-foreground" title={signal.rule_version}>실험 조건: 20 공통 관측일 10Y ≤ −30bp · HY OAS ≥ +75bp, 3회 지속. 침체 확정 신호가 아닙니다. 기대 관측일 {data.expected_date}, 2영업일 초과 지연 시 평가 보류. {data.calendar_note}. 차트는 실제 확보한 기간만 표시합니다.</p>
  </section>
}
