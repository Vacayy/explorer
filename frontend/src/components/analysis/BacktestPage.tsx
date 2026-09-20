import { useCallback, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Download, History, LoaderCircle, Plus, Square } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { PageHeader, PageLayout } from '@/components/shared/PageLayout'
import { ErrorState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { backtestArtifactUrl, isBacktestActive, useBacktest } from '@/hooks/useBacktest'
import type { BacktestConfig, BacktestRun, BacktestSegment, BacktestSpec, BacktestStatus, BacktestStrategy } from './backtestTypes'

const STATUS: Record<BacktestStatus, string> = {
  queued: '대기', preparing: '데이터 준비', running: '비교 계산 중', partial: '완료 · 잠정 결과',
  failed: '실행 오류', cancelled: '취소됨', interrupted: '실행 중단',
}
const STAGE: Record<string, string> = {
  queued: '실행을 기다리고 있습니다.', preparing: '공통 비교 데이터를 준비하고 있습니다.',
  snapshot: '비교에 사용할 시장 데이터를 고정하고 있습니다.', isolation: '계산 환경을 준비하고 있습니다.',
  running: '개발·평가 구간의 일별 거래와 자산을 계산하고 있습니다.', calculation: '개발·평가 구간의 일별 거래와 자산을 계산하고 있습니다.',
  verification: '계산 결과를 확인하고 있습니다.', validating: '계산 결과를 확인하고 있습니다.',
  checking_ledger: '거래·평가 원장 검증 중입니다.',
  finalizing: '결과와 다운로드 파일을 정리하고 있습니다.', cancelling: '실행을 중단하고 있습니다.',
}
const COLORS = ['#64748b', '#2563eb', '#0d9488', '#9333ea', '#d97706', '#db2777', '#dc2626']
const UNFILLED_REASON: Record<string, string> = {
  missing_execution_bar: '체결일 가격 없음', invalid_execution_bar: '체결일 가격 오류', invalid_open: '유효한 시가 없음',
  invalid_execution_open: '체결일 시가 오류', unknown_execution_volume: '체결일 거래량 확인 불가',
  zero_execution_volume: '체결일 거래량 0', insufficient_cash: '매수 자금 부족', no_next_session_in_segment: '구간 내 다음 체결일 없음',
}
const DATA_REASON: Record<string, string> = {
  market_not_selected: '선택한 시장에 속하지 않음', insufficient_calendar_warmup: '계산 준비에 필요한 거래일 부족',
  missing_start_bar: '구간 시작일 가격 없음', incomplete_common_warmup: '공통 준비 기간의 가격 자료 부족',
  missing_or_invalid_signal_bar: '판단일 가격 누락 또는 오류', missing_signal_date_market_cap: '판단일 시가총액 없음',
  incomplete_signal_history: '신호 계산에 필요한 과거 자료 부족',
}
const integer = (value: number) => Number.isFinite(value) ? Math.round(value).toLocaleString('ko-KR') : '—'
const decimal = (value: number, digits = 2) => Number.isFinite(value) ? value.toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '—'
const percent = (value: number) => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${decimal(value)}%` : '—'
const errorMessage = (run: BacktestRun) => typeof run.error === 'string' ? run.error : run.error?.message ?? '실행 결과가 생성되지 않았습니다. 조건과 실행 이력을 확인해주세요.'

function bounds(config: BacktestConfig, key: keyof BacktestSpec, fallback: { min: number; max: number }) {
  const value = config.limits[key]
  if (!value || typeof value !== 'object') return fallback
  const bound = value as { min?: number; max?: number }
  return { min: typeof bound.min === 'number' ? bound.min : fallback.min, max: typeof bound.max === 'number' ? bound.max : fallback.max }
}

function Warnings({ warnings }: { warnings: string[] }) {
  const unique = [...new Set(warnings.filter(Boolean))]
  if (!unique.length) return null
  return <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 text-sm">
    <p className="font-medium">연구용 잠정 결과</p>
    <p className="mt-1 text-muted-foreground">생존 편향이 남아 있고 표본이 짧습니다. 장기 수익성을 판단하기에는 한계가 있습니다.</p>
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium">전체 유의사항 {unique.length}개</summary>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-muted-foreground">{unique.map(warning => <li key={warning}>{warning}</li>)}</ul>
    </details>
  </div>
}

function Assumptions({ spec }: { spec: BacktestSpec }) {
  return <div className="space-y-2 text-sm text-muted-foreground">
    <p>각 구간을 {integer(spec.initial_cash)}원으로 독립 시작합니다. 종가로 수량을 결정하고 다음 관측 거래일 시가에 체결하며, 비용·시가 갭에 따라 매수 규모를 조정합니다.</p>
    <p>최대 {spec.max_positions}종목에 동일 비중을 배정하고 {spec.rebalance_every}거래일마다 재구성합니다. 후보가 부족한 몫은 현금으로 보유합니다. 단순 보유 기준은 구간 시작의 전체 고정 유니버스에 분산합니다.</p>
    <p>매수 {spec.buy_cost_bps}bp · 매도 {spec.sell_cost_bps}bp는 수수료·세금·슬리피지를 합친 가정입니다(1bp = 0.01%). 실제 요율이 아닙니다. 수정주가·분수 수량을 이용하며 종료일에는 강제 매도 없이 보유 자산을 평가합니다.</p>
  </div>
}

function ExperimentForm({ config, initial, pending, blocked, onSubmit }: {
  config: BacktestConfig; initial: BacktestSpec; pending: boolean; blocked: boolean; onSubmit: (spec: BacktestSpec) => Promise<void>
}) {
  const [spec, setSpec] = useState<BacktestSpec>(initial)
  const [validation, setValidation] = useState('')
  const submitting = useRef(false)
  const patch = <K extends keyof BacktestSpec>(key: K, value: BacktestSpec[K]) => setSpec(previous => ({ ...previous, [key]: value }))
  const numeric = (key: keyof BacktestSpec, label: string, fallback: { min: number; max: number }, step = 1, divisor = 1) => {
    const range = bounds(config, key, fallback)
    return <div className="space-y-2" key={key}>
      <Label htmlFor={`backtest-${key}`}>{label}</Label>
      <Input id={`backtest-${key}`} type="number" required min={range.min / divisor} max={range.max / divisor} step={step}
        value={Number.isFinite(spec[key] as number) ? (spec[key] as number) / divisor : ''}
        onChange={event => patch(key, event.target.value === '' ? Number.NaN : Number(event.target.value) * divisor)} />
    </div>
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (submitting.current || pending || blocked) return
    if (!(spec.start_date < spec.split_date && spec.split_date <= spec.end_date)) {
      setValidation('개발 시작일 < 평가 시작일 ≤ 종료일 순서로 입력해주세요.')
      return
    }
    if (!spec.markets.length) { setValidation('최소 한 개 시장을 선택해주세요.'); return }
    setValidation('')
    submitting.current = true
    try { await onSubmit(spec) } finally { submitting.current = false }
  }
  return <Card>
    <CardHeader><CardTitle><h2>비교 조건 고정</h2></CardTitle><p className="text-sm text-muted-foreground">같은 데이터와 매매 조건으로 7개 전략을 비교합니다. 실행할 때마다 조건과 결과를 새 이력으로 보존합니다.</p></CardHeader>
    <CardContent>
      <form className="space-y-5" onSubmit={submit} aria-label="전략 비교 조건">
        <fieldset disabled={pending} className="space-y-5">
          <legend className="sr-only">기간과 공통 매매 조건</legend>
          <div className="grid gap-4 sm:grid-cols-3">
            {([{ key: 'start_date', label: '개발 시작일' }, { key: 'split_date', label: '평가 시작일' }, { key: 'end_date', label: '종료일' }] as const).map(({ key, label }) => <div key={key} className="min-w-0 space-y-2">
              <Label htmlFor={`backtest-${key}`}>{label}</Label><Input id={`backtest-${key}`} type="date" required value={spec[key]}
                max={config.data.as_of ?? undefined} aria-describedby="backtest-date-help" aria-invalid={validation.startsWith('개발') || undefined}
                onChange={event => patch(key, event.target.value)} />
            </div>)}
          </div>
          <p id="backtest-date-help" className="text-xs text-muted-foreground">개발 구간은 평가 시작일 직전까지입니다. 각 구간은 최소 2거래일이 필요하며 자금·보유 종목을 새로 시작합니다.</p>
          <div className="grid gap-4 sm:grid-cols-3">
            {numeric('initial_cash', '구간별 시작 자금 (원)', { min: 100000, max: 100000000000 }, 10000)}
            {numeric('max_positions', '최대 편입 수 (종목)', { min: 1, max: 100 })}
            {numeric('rebalance_every', '재구성 주기 (거래일)', { min: 5, max: 60 })}
            {numeric('buy_cost_bps', '매수 비용 (bp)', { min: 0, max: 1000 }, 0.1)}
            {numeric('sell_cost_bps', '매도 비용 (bp)', { min: 0, max: 1000 }, 0.1)}
            {numeric('min_market_cap', '시가총액 하한 (억원)', { min: 0, max: 1000000000000000 }, 1, 100000000)}
          </div>
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium">시장</legend>
            <div className="flex flex-wrap gap-4">{['KOSPI', 'KOSDAQ'].map(market => <label key={market} className="flex min-h-10 cursor-pointer items-center gap-2 text-sm">
              <input type="checkbox" className="size-4 accent-primary" checked={spec.markets.includes(market)}
                onChange={event => patch('markets', event.target.checked ? [...spec.markets, market] : spec.markets.filter(value => value !== market))} />{market}
            </label>)}</div>
            <p className="text-xs text-muted-foreground">시총 하한이 0이면 필터를 적용하지 않습니다. 하한을 설정하면 판단일 시총이 없는 종목은 평가에서 제외됩니다.</p>
          </fieldset>
        </fieldset>
        <details className="rounded-xl bg-muted/40 p-3"><summary className="cursor-pointer text-sm font-medium">공통 매매 가정과 7개 전략</summary>
          <div className="mt-3 space-y-4"><Assumptions spec={spec} /><dl className="grid gap-3 border-t pt-3 sm:grid-cols-2">{config.strategies.map(strategy => <div key={strategy.id}><dt className="text-sm font-medium">{strategy.label}</dt><dd className="mt-1 text-xs leading-relaxed text-muted-foreground">{strategy.description}</dd></div>)}</dl></div>
        </details>
        {validation && <p id="backtest-validation" role="alert" className="text-sm text-destructive">{validation}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={pending || blocked} className="min-h-11">{pending && <LoaderCircle className="size-4 animate-spin" />}조건 고정 후 7개 전략 비교</Button>
          <span className="text-xs text-muted-foreground">{blocked ? '진행 중인 비교가 끝나면 새 실험을 실행할 수 있습니다.' : '결과를 보고 조건을 변경하면 별도 실험으로 기록됩니다.'}</span>
        </div>
      </form>
    </CardContent>
  </Card>
}

function EquityChart({ strategies, initialCash }: { strategies: BacktestStrategy[]; initialCash: number }) {
  const points = useMemo(() => {
    const rows = new Map<string, Record<string, string | number>>()
    for (const strategy of strategies) for (const point of strategy.equity) {
      if (!Number.isFinite(point.nav) || initialCash <= 0) continue
      const row = rows.get(point.date) ?? { date: point.date }
      row[strategy.id] = point.nav / initialCash * 100
      rows.set(point.date, row)
    }
    return [...rows.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)))
  }, [strategies, initialCash])
  return <div className="min-w-0 space-y-3">
    <p className="text-sm font-medium">누적 자산 곡선 <span className="font-normal text-muted-foreground">· 초기 자금 = 100, 비용 반영</span></p>
    {!points.length ? <p className="py-12 text-center text-sm text-muted-foreground">표시할 일별 평가 데이터가 없습니다.</p> : <div className="h-72 min-w-0 sm:h-80" role="img" aria-label="7개 전략의 초기 자금 대비 일별 자산 곡선. 정확한 수익률은 아래 비교표에서 확인할 수 있습니다.">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 12, right: 12, bottom: 8, left: 0 }} accessibilityLayer>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
          <XAxis dataKey="date" tickFormatter={date => String(date).slice(5)} minTickGap={35} tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }} />
          <YAxis width={46} domain={['auto', 'auto']} tickFormatter={value => decimal(Number(value), 0)} tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }} />
          <ReferenceLine y={100} stroke="var(--muted-foreground)" strokeDasharray="3 3" />
          <Tooltip formatter={(value, name) => [decimal(Number(value)), name]} labelFormatter={label => String(label)}
            contentStyle={{ backgroundColor: 'var(--popover)', color: 'var(--popover-foreground)', borderColor: 'var(--border)', borderRadius: 8, fontSize: 12 }} />
          {strategies.map((strategy, index) => <Line key={strategy.id} dataKey={strategy.id} name={strategy.label} stroke={COLORS[index % COLORS.length]} strokeWidth={1.8}
            strokeDasharray={index === 0 ? '5 3' : index >= 5 ? '3 2' : undefined} dot={false} isAnimationActive={false} connectNulls={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>}
    <ul className="flex flex-wrap gap-x-4 gap-y-2 text-xs">{strategies.map((strategy, index) => <li key={strategy.id} className="flex items-center gap-2"><span className="h-0.5 w-5" style={{ backgroundColor: COLORS[index % COLORS.length] }} aria-hidden="true" />{strategy.label}</li>)}</ul>
  </div>
}

function ComparisonTable({ strategies }: { strategies: BacktestStrategy[] }) {
  const baseline = strategies.find(strategy => strategy.id === 'buy_hold')?.metrics.total_return_pct
  return <div tabIndex={0} aria-label="전략별 비교표, 좁은 화면에서는 가로로 스크롤할 수 있습니다." className="min-w-0 rounded-lg focus-visible:outline-2 focus-visible:outline-ring">
    <p className="mb-2 text-xs text-muted-foreground sm:hidden">표를 좌우로 밀면 낙폭·비용·체결 수를 볼 수 있습니다.</p>
    <Table>
      <caption className="sr-only">전략별 수익률·위험·비용 비교. 수익률은 해당 구간 전체 수익률이며 연율화하지 않았습니다.</caption>
      <TableHeader><TableRow><TableHead>전략</TableHead><TableHead className="text-right">구간 수익률</TableHead><TableHead className="text-right">보유 기준 차이</TableHead><TableHead className="text-right">최대 낙폭</TableHead><TableHead className="text-right">평균 노출</TableHead><TableHead className="text-right">거래 비용 (원)</TableHead><TableHead className="text-right">체결 건수</TableHead><TableHead className="text-right">종료 자산 (원)</TableHead></TableRow></TableHeader>
      <TableBody>{strategies.map(strategy => <TableRow key={strategy.id}>
        <TableHead scope="row" className="font-normal">{strategy.label}{strategy.metrics.trades_count === 0 && <span className="ml-2 text-xs text-muted-foreground">거래 0</span>}</TableHead>
        <TableCell className="text-right tabular-nums">{percent(strategy.metrics.total_return_pct)}</TableCell>
        <TableCell className="text-right tabular-nums">{strategy.id === 'buy_hold' ? '기준' : baseline === undefined ? '—' : `${decimal(strategy.metrics.total_return_pct - baseline)}%p`}</TableCell>
        <TableCell className="text-right tabular-nums">{decimal(strategy.metrics.max_drawdown_pct)}%</TableCell>
        <TableCell className="text-right tabular-nums">{decimal(strategy.metrics.exposure_avg_pct, 1)}%</TableCell>
        <TableCell className="text-right tabular-nums">{integer(strategy.metrics.cost_total)}</TableCell>
        <TableCell className="text-right tabular-nums">{integer(strategy.metrics.trades_count)}</TableCell>
        <TableCell className="text-right tabular-nums">{integer(strategy.metrics.ending_nav)}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    <p className="mt-2 text-xs text-muted-foreground">평균 노출은 자산 중 주식 보유 비중입니다. 체결 건수는 개별 매수·매도 건수입니다. 단순 보유는 실제 시장 지수가 아니며, 후보가 적은 전략은 현금 비중이 커집니다.</p>
  </div>
}

function EvaluationDetail({ segment }: { segment: BacktestSegment }) {
  const [strategyId, setStrategyId] = useState(segment.strategies[0]?.id ?? '')
  const strategy = segment.strategies.find(item => item.id === strategyId) ?? segment.strategies[0]
  if (!strategy) return null
  const latest = strategy.equity.at(-1)
  return <details className="rounded-xl border p-4">
    <summary className="cursor-pointer text-sm font-medium">후보·체결·종료 보유 확인</summary>
    <div className="mt-4 space-y-4">
      <div className="max-w-sm space-y-2"><Label htmlFor="backtest-detail-strategy">확인할 전략</Label>
        <select id="backtest-detail-strategy" value={strategy.id} onChange={event => setStrategyId(event.target.value)} className="h-10 w-full rounded-md border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring">
          {segment.strategies.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </div>
      <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3 lg:grid-cols-5">
        <div><dt className="text-muted-foreground">미체결 주문</dt><dd className="mt-1 font-medium tabular-nums">{integer(strategy.metrics.unfilled_orders)}건</dd></div>
        <div><dt className="text-muted-foreground">자금에 맞춰 축소 체결</dt><dd className="mt-1 font-medium tabular-nums">{integer(strategy.metrics.partial_fills ?? 0)}건</dd></div>
        <div><dt className="text-muted-foreground">지연 평가 발생일</dt><dd className="mt-1 font-medium tabular-nums">{integer(strategy.metrics.stale_valuation_days)}일</dd></div>
        <div><dt className="text-muted-foreground">종료 보유 종목</dt><dd className="mt-1 font-medium tabular-nums">{integer(latest?.positions ?? strategy.holdings.length)}개</dd></div>
        <div><dt className="text-muted-foreground">종료 현금</dt><dd className="mt-1 font-medium tabular-nums">{latest ? `${integer(latest.cash)}원` : '—'}</dd></div>
      </dl>
      {(strategy.metrics.unfilled_orders > 0 || strategy.metrics.stale_valuation_days > 0) && <p className="rounded-lg bg-amber-500/10 p-3 text-sm">체결하지 못한 주문이나 이전 종가로 평가한 보유분이 있습니다. 결과를 읽을 때 거래 원장과 평가 기록을 함께 확인해주세요.</p>}
      {!!strategy.unfilled?.length && <details className="text-sm"><summary className="cursor-pointer font-medium">미체결 사유 ({integer(strategy.unfilled.length)}건)</summary>
        <div tabIndex={0} aria-label="미체결 주문 상세" className="mt-2 max-h-80 overflow-auto focus-visible:outline-2 focus-visible:outline-ring"><Table>
          <TableHeader><TableRow><TableHead>판단일</TableHead><TableHead>체결 예정일</TableHead><TableHead>종목</TableHead><TableHead>방향</TableHead><TableHead>사유</TableHead></TableRow></TableHeader>
          <TableBody>{strategy.unfilled.slice(0, 100).map((order, index) => <TableRow key={`${order.signal_date}-${order.code}-${index}`}><TableCell>{order.signal_date}</TableCell><TableCell>{order.date ?? '없음'}</TableCell><TableCell>{order.code}</TableCell><TableCell>{order.side === 'buy' ? '매수' : '매도'}</TableCell><TableCell>{UNFILLED_REASON[order.reason] ?? order.reason}</TableCell></TableRow>)}</TableBody>
        </Table></div>{strategy.unfilled.length > 100 && <p className="mt-2 text-xs text-muted-foreground">처음 100건을 표시합니다. 전체 기록은 결과 파일에서 확인해주세요.</p>}
      </details>}
      <div tabIndex={0} aria-label="재구성 날짜별 후보와 평가 현황" className="min-w-0 focus-visible:outline-2 focus-visible:outline-ring"><Table>
        <TableHeader><TableRow><TableHead>판단일</TableHead><TableHead>체결 예정일</TableHead><TableHead className="text-right">평가 종목</TableHead><TableHead className="text-right">미평가</TableHead><TableHead className="text-right">후보</TableHead><TableHead className="text-right">목표 편입</TableHead></TableRow></TableHeader>
        <TableBody>{strategy.rebalances.map((row, index) => <TableRow key={`${row.signal_date}-${index}`}><TableCell>{row.signal_date}</TableCell><TableCell>{row.execution_date ?? '기간 내 체결일 없음'}</TableCell><TableCell className="text-right tabular-nums">{integer(row.evaluated)}</TableCell><TableCell className="text-right tabular-nums">{integer(row.unavailable)}</TableCell><TableCell className="text-right tabular-nums">{integer(row.candidates)}</TableCell><TableCell className="text-right tabular-nums">{integer(row.target_count)}</TableCell></TableRow>)}</TableBody>
      </Table></div>
      {!strategy.rebalances.length && <p className="text-sm text-muted-foreground">재구성 판단 기록이 없습니다.</p>}
      <p className="text-xs text-muted-foreground">거래 원장·일별 평가·최종 보유의 전체 기록은 아래 결과 파일에서 확인할 수 있습니다.</p>
    </div>
  </details>
}

function BacktestResults({ run }: { run: BacktestRun }) {
  const [segmentId, setSegmentId] = useState('development')
  const result = run.result!
  const segment = result.segments.find(item => item.id === segmentId) ?? result.segments[0]
  if (!segment) return <ErrorState message="실행 결과에 비교 구간이 없습니다." />
  const excluded = Object.values(segment.universe.excluded_by_reason).reduce((sum, count) => sum + count, 0)
  return <div className="space-y-5">
    <Warnings warnings={result.warnings} />
    <Card><CardHeader><CardTitle><h2>동일 조건 비교</h2></CardTitle><p className="text-sm text-muted-foreground">짧은 표본과 현재 데이터의 제약을 포함한 연구용 결과입니다. 개발 구간과 평가 구간의 결과를 함께 확인해주세요.</p></CardHeader>
      <CardContent className="min-w-0 space-y-5">
        <SegmentTabs tabs={result.segments.map(item => ({ value: item.id, label: item.label }))} value={segment.id} onChange={setSegmentId} />
        <div className="flex flex-wrap justify-between gap-2 text-sm"><p className="font-medium">{segment.start_date} ~ {segment.end_date}</p><p className="text-muted-foreground">대상 {integer(segment.universe.requested)} · 시작 유니버스 {integer(segment.universe.eligible)} · 제외 {integer(excluded)}</p></div>
        {!!excluded && <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">구간 시작 시 제외 사유</summary><dl className="mt-2 space-y-1">{Object.entries(segment.universe.excluded_by_reason).map(([reason, count]) => <div key={reason} className="flex flex-wrap justify-between gap-3"><dt>{DATA_REASON[reason] ?? reason}</dt><dd>{integer(count)}종목</dd></div>)}</dl></details>}
        <EquityChart strategies={segment.strategies} initialCash={result.spec.initial_cash} />
        <ComparisonTable strategies={segment.strategies} />
        <EvaluationDetail key={segment.id} segment={segment} />
      </CardContent>
    </Card>
    <Card><CardHeader><CardTitle><h2>결과 파일</h2></CardTitle></CardHeader><CardContent className="space-y-3">
      <div className="flex flex-wrap gap-2">{run.artifacts.map(artifact => <Button asChild variant="outline" size="sm" key={artifact.name} className="max-w-full"><a href={backtestArtifactUrl(run.id, artifact.name)} download={artifact.name}><Download className="size-4 shrink-0" /><span className="truncate">{artifact.label || artifact.name}</span></a></Button>)}</div>
      {!run.artifacts.length && <p className="text-sm text-muted-foreground">등록된 다운로드 파일이 없습니다.</p>}
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">실험 버전과 재현 정보</summary><pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted/50 p-3">{JSON.stringify({ version: result.version, run_id: run.id, created_at: run.created_at, provenance: result.provenance }, null, 2)}</pre></details>
    </CardContent></Card>
  </div>
}

export default function BacktestPage() {
  const [params, setParams] = useSearchParams()
  const runId = params.get('run')
  const [draft, setDraft] = useState<BacktestSpec | null>(null)
  const openRun = useCallback((id: string) => setParams({ run: id }), [setParams])
  const backtest = useBacktest(runId, openRun)
  const run = backtest.detail.data
  const active = isBacktestActive(run?.status)
  const otherActive = backtest.runs.data?.items.find(item => isBacktestActive(item.status))
  const newRun = (spec?: BacktestSpec) => { setDraft(spec ?? null); setParams({}) }
  const mutationError = backtest.start.error ?? backtest.cancel.error
  const showForm = !runId && !!backtest.config.data
  return <PageLayout header={<PageHeader title="전략 비교" description="신호의 추가 효과를 같은 기간·비용·매매 규칙으로 확인합니다." actions={<>
    <Button asChild variant="ghost" size="sm"><Link to="/discover"><ArrowLeft className="size-4" />종목 발견</Link></Button>
    {runId && <Button variant="outline" size="sm" onClick={() => newRun()}><Plus className="size-4" />새 비교</Button>}
  </>} />}>
    <div className="min-w-0 space-y-5 pb-6">
      <details className="rounded-xl border p-4"><summary className="cursor-pointer text-sm font-medium"><History className="mr-2 inline size-4" />실행 이력{backtest.runs.data ? ` (${backtest.runs.data.items.length})` : ''}</summary>
        <div className="mt-3 max-h-72 space-y-1 overflow-y-auto">
          {backtest.runs.isLoading && <p className="p-3 text-sm text-muted-foreground">실행 이력을 불러오고 있습니다.</p>}
          {backtest.runs.isError && <ErrorState message="실행 이력을 불러오지 못했습니다." onRetry={() => { void backtest.runs.refetch() }} />}
          {backtest.runs.data?.items.length === 0 && <p className="p-3 text-sm text-muted-foreground">아직 실행한 비교가 없습니다.</p>}
          {backtest.runs.data?.items.map(item => <Button key={item.id} variant={item.id === runId ? 'secondary' : 'ghost'} className="h-auto min-h-12 w-full flex-wrap justify-start gap-x-3 gap-y-1 whitespace-normal px-3 py-3 text-left" onClick={() => openRun(item.id)} aria-current={item.id === runId ? 'page' : undefined}>
            <span>{item.spec.start_date} ~ {item.spec.end_date}</span><span className="text-xs font-normal text-muted-foreground">평가 {item.spec.split_date} · {STATUS[item.status]} · {new Date(item.created_at).toLocaleString('ko-KR')}</span>
          </Button>)}
        </div>
      </details>
      {!runId && backtest.config.isLoading && <div role="status" className="space-y-3"><span className="sr-only">비교 조건을 불러오고 있습니다.</span><Skeleton className="h-20" /><Skeleton className="h-72" /></div>}
      {!runId && backtest.config.isError && <ErrorState message={backtest.config.error.message} onRetry={() => { void backtest.config.refetch() }} />}
      {showForm && <>
        <Warnings warnings={backtest.config.data!.warnings} />
        {otherActive && <div className="flex flex-wrap items-center gap-3 rounded-xl border p-4 text-sm"><LoaderCircle className="size-4 animate-spin" /><span>진행 중인 비교가 있습니다.</span><Button variant="outline" size="sm" onClick={() => openRun(otherActive.id)}>실행 보기</Button></div>}
        <ExperimentForm key={JSON.stringify(draft)} config={backtest.config.data!} initial={draft ?? backtest.config.data!.defaults} pending={backtest.start.isPending} blocked={!!otherActive}
          onSubmit={async spec => { try { await backtest.start.mutateAsync(spec) } catch { /* Preserve conditions and show the request error below. */ } }} />
      </>}
      {runId && backtest.detail.isLoading && <div role="status"><p className="sr-only">실행을 불러오고 있습니다.</p><Skeleton className="h-72" /></div>}
      {runId && backtest.detail.isError && <ErrorState message={backtest.detail.error.message} onRetry={() => { void backtest.detail.refetch() }} />}
      {mutationError && <div role="alert" className="rounded-xl border border-destructive/30 p-4 text-sm text-destructive">{mutationError.message}{backtest.start.error && <p className="mt-2 text-muted-foreground">연결 오류라면 실행 이력을 확인한 뒤 다시 시도해주세요. 자동으로 재실행하지 않습니다.</p>}</div>}
      {run && <>
        <Card><CardContent className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><div role="status" className="flex items-center gap-2">{active && <LoaderCircle className="size-4 animate-spin" />}<Badge variant="secondary">{STATUS[run.status]}</Badge><span className="text-xs text-muted-foreground">{new Date(run.created_at).toLocaleString('ko-KR')}</span></div>
            {active ? <Button variant="outline" size="sm" disabled={backtest.cancel.isPending} onClick={() => backtest.cancel.mutate()}><Square className="size-3" />{backtest.cancel.isPending ? '취소 요청 중' : '실행 취소'}</Button> : <Button variant="outline" size="sm" onClick={() => newRun(run.spec)}>이 조건으로 새 비교</Button>}
          </div>
          {active && <p className="text-sm text-muted-foreground">{STAGE[run.stage] ?? STAGE.running} 화면을 나가도 실행은 계속됩니다.</p>}
          {['failed', 'interrupted', 'cancelled'].includes(run.status) && <p role={run.status === 'failed' ? 'alert' : undefined} className="text-sm text-muted-foreground">{run.status === 'cancelled' ? '비교 실행이 취소되었습니다.' : run.status === 'interrupted' ? '실행이 중단되었습니다. 새 비교로 다시 실행할 수 있습니다.' : errorMessage(run)}</p>}
          <details><summary className="cursor-pointer text-sm font-medium">저장된 실험 조건</summary><div className="mt-3 space-y-3"><p className="text-sm">개발 {run.spec.start_date} ~ 평가 시작 전 · 평가 {run.spec.split_date} ~ {run.spec.end_date}</p><p className="text-sm text-muted-foreground">{run.spec.markets.join(', ')} · 시총 하한 {integer(run.spec.min_market_cap / 100000000)}억원</p><Assumptions spec={run.spec} /></div></details>
        </CardContent></Card>
        {run.result && <BacktestResults key={run.id} run={run} />}
        {run.status === 'partial' && !run.result && <ErrorState message="완료된 실행의 결과를 불러오지 못했습니다." onRetry={() => { void backtest.detail.refetch() }} />}
      </>}
    </div>
  </PageLayout>
}
