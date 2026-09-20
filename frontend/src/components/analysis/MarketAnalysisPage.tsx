import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ChevronDown, CornerDownRight, Download, History, Library, LoaderCircle, Plus, Search, SlidersHorizontal, Square } from 'lucide-react'
import { PageHeader, PageLayout } from '@/components/shared/PageLayout'
import { ErrorState } from '@/components/shared/ErrorState'
import { FreshnessStamp } from '@/components/shared/FreshnessStamp'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { analysisArtifactUrl, useAnalysisThread, useMarketAnalysis, type ThreadTurn as Turn } from '@/hooks/useMarketAnalysis'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import { AnalysisConditions } from '@/components/analysis/AnalysisConditions'
import { AnalysisQuestion } from '@/components/analysis/AnalysisQuestion'
import { AnalysisResults } from '@/components/analysis/AnalysisResults'
import { QuestionRefiner } from '@/components/analysis/QuestionRefiner'
import { StrategyLibrary, type StrategySubmission } from '@/components/analysis/StrategyLibrary'
import { DiscoveryLibrary, DiscoveryRecommendations, SaveDiscoveryStrategy } from '@/components/analysis/DiscoveryLibrary'
import { DiscoveryFollowup, type FollowupSubmission } from '@/components/analysis/DiscoveryFollowup'
import { isTerminal } from '@/components/analysis/events'
import type { AnalysisRun, RunStatus } from '@/components/analysis/types'

const EXAMPLES = [
  { label: '강한 추세', question: '시가총액 5000억원 이상 종목 중 52주 신고가를 돌파하고 최근 14거래일 동안 20일 이동평균 위를 유지한 종목을 찾아줘' },
  { label: '거래량 변화', question: '20일과 60일 이동평균이 정배열이고 전일 대비 거래량이 증가한 종목을 찾아줘' },
  { label: '패턴 돌파', question: '시가총액 5000억원 이상 종목 중 최근 90 영업일 이내 역헤드앤숄더 패턴 이후 넥라인과 52주 신고가를 차례로 돌파하고, 최근 14영업일 동안 20일 이평선 아래로 내려간 적 없는 종목을 찾아줘' },
]
const WITHIN_OPTIONS = [{ value: 1, label: '기준일 당일' }, { value: 3, label: '최근 3거래일' }, { value: 5, label: '최근 5거래일' }, { value: 10, label: '최근 10거래일' }, { value: 20, label: '최근 20거래일' }, { value: 60, label: '최근 60거래일' }]
const STATUS: Record<RunStatus, string> = { queued: '대기', preparing: '데이터 준비', running: '분석 중', waiting_input: '조건 확인', completed: '완료', partial: '일부 평가', blocked: '진행 불가', failed: '실행 오류', cancelled: '취소됨', interrupted: '실행 중단' }
const PHASE: Record<string, string> = { queued: '실행을 기다리고 있습니다', preparing: '보유 시장 데이터를 준비하고 있습니다', isolation: '안전한 분석 환경을 확인하고 있습니다', snapshot: '분석 기준일의 데이터를 준비하고 있습니다', interpretation: '분석 조건을 확인하고 있습니다', interpreting: '요청 조건을 해석하고 있습니다', planning: '분석 조건을 정리하고 있습니다', analysis: '요청한 조건을 분석하고 있습니다', calculation: '조건에 맞는 종목을 계산하고 있습니다', executing: '조건에 맞는 종목을 계산하고 있습니다', verification: '계산 결과와 종목별 근거를 검증하고 있습니다', validating: '계산 결과와 종목별 근거를 검증하고 있습니다', finalizing: '결과를 정리하고 있습니다', cancelling: '분석을 중단하고 있습니다', finished: '실행이 끝났습니다', done: '실행이 끝났습니다', waiting_input: '입력한 조건으로 분석을 이어갑니다' }

const FIELD_LABELS: Record<string, string> = { min_market_cap: '최소 시가총액', strategy_conditions: '전략 조건', expression: '복합 조건식', universe_codes: '대상 종목', market: '시장', ma_period: '이동평균 기간', hold_days: '유지 기간', lookback_days: '탐색 기간', require_52w: '52주 신고가 조건', pattern: '패턴', mode: '검색 방식', as_of: '기준일', include_same_day: '같은 날 포함', window_scope: '탐색 구간', pivot_width: '피벗 폭', shoulder_tolerance: '어깨 허용 오차', price_adjustment: '수정주가' }
function ThreadTurn({ turn, onOpen }: { turn: Turn; onOpen: (id: string) => void }) {
  const changes = turn.lineage?.changes ?? []
  const matched = turn.result?.counts.matched
  return <Button variant="ghost" className="h-auto w-full flex-col items-stretch gap-1 whitespace-normal rounded-xl bg-card p-4 text-left" onClick={() => onOpen(turn.id)} aria-label={`${turn.question} 결과 다시 보기`}>
    <span className="flex flex-wrap items-center gap-2 text-caption font-normal text-muted-foreground">{turn.parent_run_id && <CornerDownRight className="size-3.5" aria-hidden="true" />}<Badge variant="outline">{STATUS[turn.status]}</Badge>{matched != null && <span>후보 {formatNumber(matched)}개</span>}<span className="ml-auto">{formatRelativeTime(turn.created_at)}</span></span>
    <span className="line-clamp-2 text-sm font-medium">{turn.question}</span>
    {changes.length > 0 && <span className="text-caption font-normal text-muted-foreground">바뀐 조건 · {changes.map(change => FIELD_LABELS[change.field] ?? change.field).join(' · ')}</span>}
  </Button>
}

function RunHistory({ runs, selected, onOpen }: { runs: AnalysisRun[]; selected: string | null; onOpen: (id: string) => void }) {
  return <div className="space-y-1">{runs.map(run => <Button key={run.id} variant={run.id === selected ? 'secondary' : 'ghost'} className="h-auto w-full flex-col items-start gap-1 whitespace-normal px-3 py-3 text-left" onClick={() => onOpen(run.id)} aria-current={run.id === selected ? 'page' : undefined}>
    <span className="line-clamp-2 text-sm font-normal">{run.question}</span><span className="text-caption font-normal text-muted-foreground">{STATUS[run.status]} · {formatRelativeTime(run.created_at)}</span>
  </Button>)}</div>
}

function AnalysisWorkspace({ runId, initialQuestion, onOpen, onNew }: { runId: string | null; initialQuestion: string; onOpen: (id: string) => void; onNew: (question?: string) => void }) {
  const [params, setParams] = useSearchParams()
  const analysis = useMarketAnalysis(runId, onOpen)
  const run = analysis.detail.data
  const thread = useAnalysisThread(runId)
  const turns = thread.data?.items ?? []
  const focused = useRef<HTMLLIElement>(null)
  const scrolled = useRef(false)
  useEffect(() => {
    // Opening a later turn of a thread lands on it; earlier turns stay reachable above.
    if (scrolled.current || turns.length < 2 || turns[0].id === runId) return
    scrolled.current = true
    focused.current?.scrollIntoView({ block: 'start' })
  }, [turns, runId])
  const [question, setQuestion] = useState(initialQuestion)
  const [asOf, setAsOf] = useState('')
  const [within, setWithin] = useState(1) // 문장에 기간이 없는 조건의 판정 범위(거래일)
  const requestKey = useRef<{ input: string; key: string } | null>(null)
  const submitting = useRef(false)
  const busy = !!run && !isTerminal(run.status)
  const library = params.get('view') === 'library'
  const panel = params.get('panel')
  const warnings = [...new Set([...(run?.snapshot?.warnings ?? []), ...(run?.result?.warnings ?? []), ...(run?.result?.unsupported_conditions ?? []).map(condition => `지원하지 않는 요청 조건: ${condition}`)])]
  const mutationError = analysis.start.error ?? analysis.resume.error ?? analysis.cancel.error
  const setPanel = (value: string | null) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set('panel', value); else next.delete('panel'); return next }, { replace: true })
  const setLibrary = (value: boolean) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set('view', 'library'); else next.delete('view'); return next })

  function appendCondition(phrase: string) {
    setQuestion(previous => {
      if (previous.includes(phrase)) return previous
      const base = previous.trim() ? previous.trimEnd() : '다음 조건을 모두 만족하는 종목을 찾아줘.'
      return `${base}\n- ${phrase}`
    })
    const field = document.getElementById('analysis-question') as HTMLTextAreaElement | null
    field?.focus(); field?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  async function submit(strategy?: StrategySubmission | FollowupSubmission) {
    const body = strategy ?? { question: question.trim(), ...(asOf ? { as_of: asOf } : {}), ...(within > 1 ? { default_within_days: within } : {}) }
    if (!body.question || analysis.start.isPending || submitting.current) return
    submitting.current = true
    const input = JSON.stringify(body)
    if (requestKey.current?.input !== input) requestKey.current = { input, key: crypto.randomUUID() }
    try {
      await analysis.start.mutateAsync({ ...body, request_key: requestKey.current.key })
      requestKey.current = null
    } catch { /* Preserve input and request key for retry. */ }
    finally { submitting.current = false }
  }

  return <div className="min-w-0 space-y-5">
    <div className="flex flex-wrap items-center gap-2" aria-label="발견 작업 도구">
      <Button variant={library ? 'ghost' : 'secondary'} size="sm" onClick={() => setLibrary(false)}><Search className="size-4" />{runId ? '검색 결과' : '새 검색'}</Button>
      <Button variant={library ? 'secondary' : 'ghost'} size="sm" onClick={() => setLibrary(true)}><Library className="size-4" />저장 전략·조사</Button>
      <div className="ml-auto flex flex-wrap gap-1">
        <Sheet open={panel === 'tools'} onOpenChange={open => setPanel(open ? 'tools' : null)}>
          <SheetTrigger asChild><Button variant="ghost" size="sm"><SlidersHorizontal className="size-4" />조건 직접 구성</Button></SheetTrigger>
          <SheetContent className="w-full overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
            <SheetHeader><SheetTitle>전략 도구로 조건 구성</SheetTitle><SheetDescription>계산 기준을 확인하고 원하는 신호를 조합합니다.</SheetDescription></SheetHeader>
            <div className="min-w-0 px-4 pb-6 sm:px-6"><StrategyLibrary busy={analysis.start.isPending || busy} onStart={submit} />{analysis.start.error && <p role="alert" className="mt-3 text-sm text-destructive">{analysis.start.error.message}</p>}</div>
          </SheetContent>
        </Sheet>
        <Sheet open={panel === 'history'} onOpenChange={open => setPanel(open ? 'history' : null)}>
          <SheetTrigger asChild><Button variant="ghost" size="sm"><History className="size-4" />이전 검색</Button></SheetTrigger>
          <SheetContent className="overflow-y-auto"><SheetHeader><SheetTitle>이전 검색</SheetTitle><SheetDescription>저장된 결과를 다시 열어 탐색을 이어갑니다.</SheetDescription></SheetHeader>
            <div className="px-4 pb-6">{analysis.runs.isPending && <Skeleton className="h-36 w-full" />}{analysis.runs.isError && <ErrorState message="이전 검색을 불러오지 못했습니다." onRetry={() => analysis.runs.refetch()} />}{analysis.runs.data && (analysis.runs.data.items.length ? <RunHistory runs={analysis.runs.data.items} selected={runId} onOpen={onOpen} /> : <p className="py-6 text-sm text-muted-foreground">아직 실행한 검색이 없습니다.</p>)}</div>
          </SheetContent>
        </Sheet>
      </div>
    </div>

    {library && <DiscoveryLibrary onOpen={onOpen} />}
    <div hidden={library} className="space-y-5">
      {!runId && <>
        <Card><CardHeader><h2 className="text-section font-semibold">어떤 종목을 발견하고 싶나요?</h2><p className="text-sm text-muted-foreground">원하는 흐름을 말로 적으면, 조건에 맞는 종목과 계산 근거를 찾아드립니다.</p></CardHeader>
          <CardContent><form onSubmit={event => { event.preventDefault(); void submit() }} className="space-y-3">
            <Label htmlFor="analysis-question" className="sr-only">찾고 싶은 종목의 조건</Label>
            <Textarea id="analysis-question" value={question} onChange={event => setQuestion(event.target.value)} placeholder="예: 신고가 돌파 후 거래량이 붙고, 20일 이평선 위를 유지하는 종목을 찾아줘" className="min-h-28 resize-y text-base" disabled={analysis.start.isPending} maxLength={12000} onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) { event.preventDefault(); void submit() } }} />
            <div className="flex flex-wrap items-center gap-2"><span className="text-caption text-muted-foreground">질문 예시</span>{EXAMPLES.map(example => <Button key={example.label} type="button" variant="secondary" size="sm" disabled={analysis.start.isPending} onClick={() => { setQuestion(example.question); document.getElementById('analysis-question')?.focus() }}>{example.label}</Button>)}</div>
            <QuestionRefiner question={question} disabled={analysis.start.isPending} onApply={text => { setQuestion(text); const field = document.getElementById('analysis-question') as HTMLTextAreaElement | null; field?.focus(); field?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }} />
            <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap items-center gap-2"><Label htmlFor="analysis-within" className="text-sm text-muted-foreground">판정 범위</Label><Select value={String(within)} onValueChange={value => setWithin(Number(value))} disabled={analysis.start.isPending}><SelectTrigger id="analysis-within" size="sm" className="w-auto min-w-36" aria-label="조건 판정 범위"><SelectValue /></SelectTrigger><SelectContent>{WITHIN_OPTIONS.map(option => <SelectItem key={option.value} value={String(option.value)}>{option.label}</SelectItem>)}</SelectContent></Select><span className="text-caption text-muted-foreground">문장에 기간이 없는 조건에 적용 · 순위 조건은 당일</span><Collapsible><CollapsibleTrigger asChild><Button type="button" variant="ghost" size="sm">{asOf ? `${asOf} 기준` : '최신 보유일 기준'}<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-2 pt-2"><Label htmlFor="analysis-as-of">다른 기준일 선택</Label><Input id="analysis-as-of" type="date" value={asOf} onChange={event => setAsOf(event.target.value)} disabled={analysis.start.isPending} /><p className="text-caption text-muted-foreground">비워 두면 최신 보유일을 사용합니다.</p></CollapsibleContent></Collapsible></div><Button type="submit" disabled={!question.trim() || analysis.start.isPending}>{analysis.start.isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}종목 찾기</Button></div>
          </form></CardContent>
        </Card>
        {!analysis.start.isPending && <section aria-label="추천 검색" className="space-y-3"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-card-title font-medium">목적에 맞는 검색으로 시작하기</h2><Button variant="ghost" size="sm" onClick={() => setLibrary(true)}>저장한 전략 보기</Button></div><DiscoveryRecommendations onAppend={appendCondition} compact onOpen={onOpen} /></section>}
      </>}
      {runId && analysis.detail.isPending && <div aria-label="검색 불러오는 중" role="status" className="space-y-4"><Skeleton className="h-24 w-full" /><Skeleton className="h-80 w-full" /></div>}
      {runId && analysis.detail.isError && <ErrorState message="검색 기록을 불러오지 못했습니다." onRetry={() => analysis.detail.refetch()} />}
      {mutationError && <div role="alert"><ErrorState message={mutationError.message} /></div>}
      {run && <ol aria-label="검색 스레드" className="space-y-4">{(turns.some(turn => turn.id === run.id) ? turns : [run]).map(turn => turn.id !== run.id ? <li key={turn.id}><ThreadTurn turn={turn as Turn} onOpen={onOpen} /></li> : <li key={turn.id} ref={focused} className="scroll-mt-4 space-y-5">
        <section aria-label="현재 검색" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{STATUS[run.status]}</Badge><span className="text-caption text-hypothesis">AI 조건 해석</span><span className="ml-auto"><FreshnessStamp asOf={run.updated_at} /></span>{run.result && ['completed', 'partial'].includes(run.status) && <SaveDiscoveryStrategy run={run} />}</div>
          <Collapsible><div className="flex items-start gap-2"><h2 className="min-w-0 flex-1 line-clamp-2 text-card-title font-medium leading-relaxed">{run.question}</h2><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="shrink-0">조건 상세<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger></div><CollapsibleContent className="space-y-3 rounded-xl bg-card p-4 mt-3"><p className="whitespace-pre-wrap text-sm">{run.question}</p>{run.spec && <AnalysisConditions spec={run.spec} priceAdjustment={run.snapshot?.price_adjustment?.status} definitions={run.result?.strategy_definitions} />}{run.saved_strategy && <p className="text-caption text-muted-foreground">저장 전략 {run.saved_strategy.name} · v{run.saved_strategy.version} · {run.saved_strategy.date_policy === 'fixed' ? '기준일 고정' : '최신 보유일'}</p>}{run.lineage && <p className="text-caption text-muted-foreground"><Link className="text-primary hover:underline" to={`/discover?run=${run.lineage.parent_run_id}`}>이전 검색 보기</Link> · {run.lineage.scope === 'candidates' ? '이전 후보 범위' : '이전 검색 대상 전체'} · {run.lineage.date_policy === 'same' ? '동일 데이터' : '최신 데이터'}</p>}</CollapsibleContent></Collapsible>
          {busy && <div className="space-y-2 rounded-xl bg-card p-4"><div className="flex flex-wrap items-center justify-between gap-3"><p role="status" aria-live="polite" className="flex items-center gap-2 text-sm">{run.status !== 'waiting_input' && <LoaderCircle className="size-4 animate-spin text-primary" />}{PHASE[run.phase] ?? STATUS[run.status]}</p><Button variant="outline" size="sm" disabled={analysis.cancel.isPending} onClick={() => analysis.cancel.mutate()}><Square className="size-3" />{analysis.cancel.isPending ? '취소 요청 중…' : '분석 취소'}</Button></div><p className="text-caption text-muted-foreground">화면을 나가도 실행은 이어집니다. 이전 검색에서 다시 확인할 수 있습니다.</p>{analysis.disconnected && <p className="text-caption text-muted-foreground">진행 연결을 복구하고 있습니다. 저장된 실행 상태를 확인 중입니다.</p>}</div>}
        </section>
        {run.pending && ['waiting_input', 'interrupted'].includes(run.status) && !run.cost_uncertain && <AnalysisQuestion key={run.pending.id} pending={run.pending} busy={analysis.resume.isPending || analysis.cancel.isPending} onAnswer={payload => analysis.resume.mutateAsync({ interrupt_id: run.pending!.id, payload })} />}
        {busy && run.status !== 'waiting_input' && !run.result && <div aria-label="검색 결과를 준비하고 있습니다" className="space-y-3"><Skeleton className="h-20 w-full" /><Skeleton className="h-72 w-full" /></div>}
        {(run.error || ['blocked', 'failed', 'interrupted', 'cancelled'].includes(run.status)) && <Card><CardContent className="space-y-3 pt-5"><p role="alert" className={run.status === 'cancelled' ? 'text-sm text-muted-foreground' : 'text-sm text-destructive'}>{run.error || (run.status === 'cancelled' ? '사용자 요청으로 검색을 취소했습니다.' : run.status === 'interrupted' ? run.pending && !run.cost_uncertain ? '같은 데이터와 조건으로 재개할 수 있습니다.' : '서버가 중단되어 이 실행을 계속할 수 없습니다.' : '검색을 완료하지 못했습니다.')}</p>{run.cost_uncertain && <p className="text-sm text-muted-foreground">중단된 호출의 비용을 확인할 수 없어 기존 실행을 재개할 수 없습니다. 새 검색으로 시작해 주세요.</p>}<Button variant="outline" size="sm" disabled={analysis.start.isPending} onClick={() => run.spec?.mode === 'catalog' ? void submit({ question: run.question, spec: run.spec }) : onNew(run.question)}>{run.spec?.mode === 'catalog' ? '같은 조건으로 새 검색' : '같은 질문으로 새 검색'}</Button></CardContent></Card>}
        {run.result && <AnalysisResults key={run.id} runId={run.id} result={run.result} onOpen={onOpen} warnings={warnings} />}
        {!run.result && warnings.length > 0 && <div className="rounded-xl bg-hypothesis/10 p-4"><p className="text-sm font-medium">자료 확인이 필요합니다</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></div>}
        <Collapsible className="rounded-xl bg-card px-4 py-2"><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="w-full justify-between">실행 기록·결과 파일<ChevronDown className="size-4" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-3 pb-3 pt-2">
          {!!run.artifacts.length && <div className="flex flex-wrap items-center gap-2" aria-label="검색 결과 파일">{run.artifacts.map(artifact => <Button key={artifact.id} asChild variant="outline" size="sm"><a href={analysisArtifactUrl(run.id, artifact.id)} download={artifact.name}><Download className="size-3.5" />{artifact.name}</a></Button>)}</div>}
          <p className="text-caption text-muted-foreground">{formatNumber(run.steps)}단계 · 사용 비용 ${new Intl.NumberFormat('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 }).format(run.cost_usd)} · 실행 시간 {formatNumber(Math.round(run.active_seconds))}초</p><p className="text-caption text-muted-foreground">비용은 추정치이며 입력 대기 시간은 제외합니다. 분석은 원본 시장 데이터를 변경하지 않습니다.</p>{run.snapshot && <p className="text-caption text-muted-foreground">자료 기준일 {run.snapshot.as_of} · {formatNumber(run.snapshot.stocks)}종목 · {formatNumber(run.snapshot.rows)}개 시세</p>}
          {analysis.logs.length ? <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-3 font-mono text-caption">{analysis.logs.map(log => `[${log.sequence}] ${log.text}`).join('\n\n')}</pre> : <p className="text-caption text-muted-foreground">저장된 실행 이벤트를 불러오면 여기에 표시합니다.</p>}
          <Button asChild variant="outline" size="sm"><Link to="/analysis/backtests">백테스트로 전략 비교</Link></Button>
        </CollapsibleContent></Collapsible>
      </li>)}</ol>}
      {run?.result && ['completed', 'partial'].includes(run.status) && <DiscoveryFollowup runId={run.id} busy={analysis.start.isPending} onSubmit={submit} />}
    </div>
  </div>
}

export default function MarketAnalysisPage() {
  const [params, setParams] = useSearchParams()
  const runId = params.get('run')
  const openRun = useCallback((id: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set('run', id); for (const key of ['mode', 'q', 'candidate', 'view', 'panel']) next.delete(key); return next }), [setParams])
  const newRun = (question = '') => setParams(previous => { const next = new URLSearchParams(previous); for (const key of ['mode', 'run', 'candidate', 'view', 'panel']) next.delete(key); if (question) next.set('q', question); else next.delete('q'); return next })
  return <PageLayout header={<PageHeader title="종목 발견" description="조건으로 발견하고, 근거를 조사하고, 내 판단으로 이어갑니다." actions={runId ? <Button variant="outline" size="sm" onClick={() => newRun()}><Plus className="size-4" />새 검색</Button> : params.get('view') === 'library' ? <Button variant="ghost" size="sm" onClick={() => newRun()}><ArrowLeft className="size-4" />검색으로</Button> : undefined} />}>
    <AnalysisWorkspace key={runId ?? `new:${params.get('q') ?? ''}`} runId={runId} initialQuestion={params.get('q') ?? ''} onOpen={openRun} onNew={newRun} />
  </PageLayout>
}
