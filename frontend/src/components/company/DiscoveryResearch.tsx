import { useId, useState, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, BookOpen, Building2, Check, ChevronDown, ExternalLink, History, LoaderCircle, Settings2, Square, Table2 } from 'lucide-react'
import { toast } from 'sonner'
import { AnalysisConditions } from '@/components/analysis/AnalysisConditions'
import type { DiscoveryCase, DiscoveryNote, ResearchEvidence, ResearchRun } from '@/components/analysis/discoveryTypes'
import { ErrorState } from '@/components/shared/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useDiscoveryAction, useDiscoveryCase } from '@/hooks/useDiscovery'
import { safeEvidenceUrl, evidenceText, researchStatus, claimKind, timePrecision, researchProse, discoveryPriceAdjustment } from '@/components/company/discoveryPresentation'
import { formatNumber } from '@/utils/format'
import { preparationStatus, researchPhase, researchDate } from '@/components/company/discoveryPresentation'
import { checkValue, evidenceValue } from '@/components/analysis/strategyEvidence'

const LANES = [ ['market', '시장 담론'], ['industry', '전방 산업'], ['earnings', '실적·공시'], ['call', '컨퍼런스콜'], ['trade', '수출입'] ] as const

function SourceExcerpt({ item }: { item: ResearchEvidence }) {
  if (item.hs_code && item.values?.length) return <div className="space-y-2"><p className="text-caption text-muted-foreground">HS {item.hs_code} · 저장 금액 USD / 중량 kg · 각 품목을 개별 표시</p><Table><TableHeader><TableRow>{['기간', '수출액 (USD)', '수입액 (USD)', '수출 중량 (kg)', '수입 중량 (kg)'].map(label => <TableHead key={label}>{label}</TableHead>)}</TableRow></TableHeader><TableBody>{item.values.map((row, index) => <TableRow key={index}>{['period', 'export_usd', 'import_usd', 'export_wt', 'import_wt'].map(field => <TableCell key={field} className="tabular-nums">{evidenceValue(row[field])}</TableCell>)}</TableRow>)}</TableBody></Table><p className="text-caption text-muted-foreground">저장된 0에는 원천 누락의 변환이 포함될 수 있습니다. 기업 매출로 간주하거나 서로 다른 HS 코드를 합산하지 않습니다.</p></div>
  return <blockquote className="whitespace-pre-wrap break-words rounded-lg border-l-2 border-primary bg-muted/40 p-4 text-sm leading-relaxed">{item.excerpt || '이 자료에는 표시할 원문 발췌가 없습니다.'}</blockquote>
}

function DiscoveryEvidence({ value }: { value: unknown }) {
  const evidence = value && typeof value === 'object' ? value as { status?: string; checks?: Record<string, unknown>; breakout_date?: string; high52_date?: string } : {}
  const labels: Record<string, string> = { market_cap: '시가총액', pattern: '역헤드앤숄더', high52: '52주 신고가', ma: '이동평균 유지', price_adjustment: '수정주가', calendar: '거래일 달력', event_order: '사건 순서' }
  const fields: Record<string, string> = { date: '판정일', value: '계산 값', minimum: '최소 기준', reference: '비교 기준', close: '종가', previous_high: '이전 최고가', period: '기간', hold_days: '유지 거래일', rank: '순위', window_start: '관측 시작', known_at: '확인 가능한 날' }
  return <div className="space-y-3 pt-3">{evidence.status === 'provisional' && <p className="text-sm text-hypothesis">잠정 후보 · 미검증 항목이 남아 있습니다.</p>}{evidence.breakout_date && <p className="text-caption">넥라인 돌파 {evidence.breakout_date} · 52주 신고가 {evidence.high52_date ?? '미확인'}</p>}<dl className="space-y-3">{Object.entries(evidence.checks ?? {}).map(([key, value]) => { const check = value && typeof value === 'object' ? value as Record<string, unknown> : {}; return <div key={key} className="rounded-lg bg-muted/40 p-3"><dt className="text-sm font-medium">{typeof check.label === 'string' ? check.label : labels[key] ?? key} · {checkValue(value)}</dt><dd className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-caption text-muted-foreground">{Object.entries(fields).flatMap(([field, label]) => check[field] != null ? [<span key={field}>{label} {evidenceValue(check[field])}</span>] : [])}</dd></div> })}</dl>{!Object.keys(evidence.checks ?? {}).length && <p className="text-caption text-muted-foreground">저장된 세부 계산 값이 없습니다. 원본 검색에서 전체 결과를 확인해 주세요.</p>}</div>
}

function EvidenceDetail({ item, label }: { item: ResearchEvidence; label?: string }) {
  const url = safeEvidenceUrl(item.url)
  const { stockCode } = useParams<{ stockCode: string }>()
  // Internal destinations for the evidence: stored document reader, financial tables, or the originating screen.
  const internal = item.id.startsWith('doc:') ? { to: `/doc/${encodeURIComponent(item.id.slice(4))}`, label: '저장 원문·스터디로 열기', icon: BookOpen }
    : item.id.startsWith('financial:') && stockCode ? { to: `/analyze/${stockCode}/financials`, label: '실적 표 보기', icon: Table2 }
    : item.id.startsWith('discovery:') && stockCode ? { to: `/discover?run=${encodeURIComponent(item.id.slice(10))}&candidate=${stockCode}`, label: '발견 조건·차트 보기', icon: ArrowLeft }
    : null
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="link" aria-label={label ? `${label} ${item.title}` : undefined} className="h-auto max-w-full justify-start whitespace-normal p-0 text-left text-caption">{label ?? item.title}</Button>
      </SheetTrigger>
      <SheetContent className="w-full! overflow-y-auto sm:max-w-xl!">
        <SheetHeader className="pr-14">
          <SheetTitle className="leading-relaxed">{item.title}</SheetTitle>
          <SheetDescription>{item.published_at ? `자료 날짜 ${item.published_at}` : '공개 날짜 미확인'} · {timePrecision(item.time_precision)}</SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-6 pb-8">
          <p className="text-caption text-muted-foreground">{evidenceText(item.source)}</p>
          <SourceExcerpt item={item} />
          {item.warnings?.map((warning, index) => <p key={index} className="text-caption text-muted-foreground">{warning}</p>)}
          <p className="text-caption text-muted-foreground">이번 조사에서 읽은 발췌입니다. 자료의 주장과 모델 해석을 구분해 확인하세요.</p>
          <div className="flex flex-wrap gap-2">
            {internal && <Button asChild variant="secondary" size="sm"><Link to={internal.to}><internal.icon className="size-3.5" />{internal.label}</Link></Button>}
            {url ? <Button asChild variant="outline" size="sm"><a href={url} target="_blank" rel="noopener noreferrer">원문 열기 <ExternalLink className="size-3.5" /></a></Button> : !internal && <p className="text-caption text-muted-foreground">연결된 원문 URL이 없습니다.</p>}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}

function Fold({ title, children }: { title: ReactNode; children: ReactNode }) {
  return <Collapsible className="min-w-0 border-t pt-3">
    <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="h-auto w-full justify-between gap-3 whitespace-normal text-left">{title}<ChevronDown className="size-4 shrink-0" /></Button></CollapsibleTrigger>
    <CollapsibleContent className="pt-3">{children}</CollapsibleContent>
  </Collapsible>
}

function ResearchPacket({ run }: { run: ResearchRun }) {
  const [sp, setSp] = useSearchParams()
  const laneId = LANES.some(([id]) => id === sp.get('lane')) ? sp.get('lane')! : 'market'
  const packet = run.packet
  if (!packet) return null
  return <div className="space-y-4"><div><h3 className="font-medium">읽은 자료와 자료 공백</h3><p className="text-caption text-muted-foreground">자료 기준 {packet.as_of} · 각 항목을 열면 이번 조사에 사용한 원문 발췌를 볼 수 있습니다.</p></div>
    {!!packet.warnings.length && <ul className="list-disc space-y-1 pl-5 text-caption text-muted-foreground">{packet.warnings.map((text, index) => <li key={index}>{text}</li>)}</ul>}
    <Tabs value={laneId} onValueChange={value => setSp(prev => { const next = new URLSearchParams(prev); next.set('lane', value); return next }, { replace: true })}><TabsList aria-label="리서치 자료 분야" className="h-auto! w-full flex-wrap justify-start rounded-lg">{LANES.map(([id, label]) => <TabsTrigger key={id} value={id} className="min-h-9 flex-none">{label} <span className="text-muted-foreground">{packet.lanes.find(lane => lane.id === id)?.items.length ?? 0}</span></TabsTrigger>)}</TabsList>
      {LANES.map(([id, label]) => { const lane = packet.lanes.find(value => value.id === id); return <TabsContent key={id} value={id} className="space-y-3 pt-3"><div className="flex flex-wrap items-center gap-2"><h4 className="text-sm font-medium">{label}</h4><Badge variant="outline">{researchStatus(lane?.status ?? 'unknown')}</Badge></div>{lane?.warnings.map((text, index) => <p key={index} className="text-caption text-muted-foreground">{text}</p>)}{!lane?.items.length && <p className="py-3 text-sm text-muted-foreground">이번 조사에서 근거를 확보하지 못했습니다. 위 자료 준비 상태와 분야별 확인 사항을 참고하세요.</p>}{lane?.items.map(item => <article key={item.id} className="space-y-2 rounded-lg border p-3"><EvidenceDetail item={item} /><p className="line-clamp-3 whitespace-pre-wrap text-sm text-muted-foreground">{item.hs_code ? `HS ${item.hs_code} · ${item.period ?? '기간 확인 필요'} · 저장 수출입 통계. 기업과 품목의 연결은 미검증입니다.` : item.excerpt}</p><p className="text-caption text-muted-foreground">{item.published_at ?? '공개 날짜 미확인'} · {evidenceText(item.source)}</p></article>)}</TabsContent> })}
    </Tabs>
  </div>
}

/** Stored summaries keep their citations; present known IDs as source links rather than raw IDs. */
function ResearchText({ text, evidence }: { text: string; evidence: Map<string, ResearchEvidence> }) {
  const content = researchProse(text)
  const parts: ReactNode[] = []
  let offset = 0
  for (const match of content.matchAll(/\[([a-z_]+:[^\]]+)\]/g)) {
    parts.push(content.slice(offset, match.index))
    const item = evidence.get(match[1])
    parts.push(item ? <EvidenceDetail key={match.index} item={item} label={`[${[...evidence.keys()].indexOf(item.id) + 1}]`} /> : <span key={match.index} className="text-caption text-muted-foreground">[인용 자료 미확인]</span>)
    offset = match.index! + match[0].length
  }
  parts.push(content.slice(offset))
  return <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{parts}</p>
}

function ResearchAnswer({ run }: { run: ResearchRun }) {
  if (!run.result) return null
  const evidence = new Map(run.packet?.lanes.flatMap(lane => lane.items).map(item => [item.id, item]) ?? [])
  return <div className="space-y-4"><h3 className="font-medium">근거를 연결한 조사 결과</h3><ResearchText text={run.result.summary} evidence={evidence} />
    <div className="space-y-3">{run.result.claims.map((claim, index) => <article key={index} className="space-y-2 rounded-lg border p-4"><Badge variant={claim.kind === 'inference' ? 'secondary' : 'outline'}>{claimKind(claim.kind)}</Badge><ResearchText text={claim.text} evidence={evidence} /><div className="flex flex-wrap gap-x-4 gap-y-2">{claim.evidence_ids.map(id => { const item = evidence.get(id); return item ? <EvidenceDetail key={id} item={item} label={`근거 · ${item.title}`} /> : <span key={id} className="text-caption text-muted-foreground">인용 자료를 찾을 수 없습니다.</span> })}</div></article>)}</div>
    {!!run.result.questions.length && <div className="space-y-2"><h4 className="text-sm font-medium">다음에 확인할 질문</h4><ul className="list-disc space-y-1 pl-5 text-sm">{run.result.questions.map((question, index) => <li key={index}>{researchProse(question)}</li>)}</ul></div>}
    {!!run.result.limitations.length && <div className="space-y-2"><h4 className="text-sm font-medium">해석의 한계</h4><ul className="list-disc space-y-1 pl-5 text-caption text-muted-foreground">{run.result.limitations.map((text, index) => <li key={index}>{researchProse(text)}</li>)}</ul></div>}
  </div>
}

function ResearchChanges({ run, history }: { run: ResearchRun; history: ResearchRun[] }) {
  const changes = run.changes
  if (!changes?.previous_run_id) return null
  const previous = history.find(item => item.id === changes.previous_run_id)
  const now = new Map(run.packet?.lanes.flatMap(lane => lane.items).map(item => [item.id, item]) ?? [])
  const before = new Map(previous?.packet?.lanes.flatMap(lane => lane.items).map(item => [item.id, item]) ?? [])
  const groups = [ ['이번에 포함된 근거', changes.added_ids, now], ['내용이 바뀐 근거', changes.changed_ids ?? [], now], ['이번 자료 묶음에 없는 이전 근거', changes.removed_ids, before] ] as const
  return <Fold title="이전 조사 이후 달라진 자료"><div className="space-y-3 rounded-lg bg-muted/50 p-4"><p className="text-caption text-muted-foreground">{previous?.created_at.slice(0, 10) ?? '이전 실행'}과 비교한 자료 묶음의 차이입니다. 목록에서 빠졌다고 원문이 삭제되거나 가설이 틀렸다는 뜻은 아닙니다.</p>{groups.map(([label, ids, map]) => <div key={label} className="space-y-2"><h4 className="text-caption font-medium">{label} · {ids.length}건</h4>{ids.length > 0 && <ul className="space-y-1">{ids.map(id => <li key={id}>{map.has(id) ? <EvidenceDetail item={map.get(id)!} /> : <span className="text-caption text-muted-foreground">이 자료의 발췌를 불러오지 못했습니다.</span>}</li>)}</ul>}</div>)}</div></Fold>
}

function NoteDetails({ note }: { note: DiscoveryNote }) {
  return <dl className="space-y-3 text-sm">{[['관심을 갖는 이유', note.reason], ['성립해야 할 가정', note.assumptions], ['생각을 바꿀 조건', note.invalidation], ['다음 확인 항목', note.watch_items.join('\n')]].map(([label, value]) => <div key={label}><dt className="mb-1 text-caption text-muted-foreground">{label}</dt><dd className="whitespace-pre-wrap">{value || '기록하지 않음'}</dd></div>)}</dl>
}

function JudgmentForm({ item }: { item: DiscoveryCase }) {
  const latest = [...item.notes].sort((a, b) => b.revision - a.revision)[0]
  const [baseRevision, setBaseRevision] = useState(latest?.revision ?? 0)
  const id = useId()
  const [reason, setReason] = useState(latest?.reason ?? '')
  const [assumptions, setAssumptions] = useState(latest?.assumptions ?? '')
  const [invalidation, setInvalidation] = useState(latest?.invalidation ?? '')
  const [watch, setWatch] = useState(latest?.watch_items.join('\n') ?? '')
  const save = useDiscoveryAction<DiscoveryCase>()
  const newerRecord = (latest?.revision ?? 0) > baseRevision
  const watchItems = watch.split('\n').map(value => value.trim()).filter(Boolean)
  const watchError = watchItems.length > 20 ? '다음 확인 항목은 최대 20개입니다.' : watchItems.some(value => value.length > 1000) ? '각 확인 항목은 1,000자 이내로 적어 주세요.' : null
  async function submit() {
    if (save.isPending || !reason.trim() || newerRecord || watchError) return
    try {
      const saved = await save.mutateAsync({ path: `/cases/${item.id}/notes`, body: { expected_revision: baseRevision, reason: reason.trim(), assumptions: assumptions.trim(), invalidation: invalidation.trim(), watch_items: watchItems } })
      setBaseRevision(Math.max(0, ...saved.notes.map(note => note.revision)))
      toast.success('내 판단을 새 버전으로 저장했습니다.')
    } catch { /* Preserve user input on revision conflict/network failure. */ }
  }
  return <div className="space-y-5"><form className="space-y-4" onSubmit={event => { event.preventDefault(); void submit() }}><p className="text-caption text-muted-foreground">근거를 읽으며 내 생각을 기록하세요. 이전 판단은 버전으로 남습니다.</p>{newerRecord && <div role="status" className="space-y-3 rounded-lg bg-muted p-3"><p className="text-sm">다른 곳에서 v{latest!.revision} 기록이 추가되었습니다. 작성 중인 내용은 유지했습니다. 아래 이력을 확인한 뒤 새 버전으로 이어서 저장할 수 있습니다.</p><Button variant="outline" size="sm" type="button" onClick={() => setBaseRevision(latest!.revision)}>현재 초안을 v{latest!.revision} 다음에 저장하기</Button></div>}{([
    ['reason', '관심을 갖는 이유', reason, setReason, '가격 신호를 넘어서 어떤 기회를 보고 있나요?'],
    ['assumptions', '성립해야 할 가정', assumptions, setAssumptions, '예: 고객사의 주문 확대가 실제 매출로 이어져야 한다.'],
    ['invalidation', '생각을 바꿀 조건', invalidation, setInvalidation, '예: 수요 확대 가설을 반박하는 실적이나 공시'],
    ['watch', '다음 확인 항목 · 최대 20개, 한 줄에 하나', watch, setWatch, '다음 실적 발표에서 주문 추이 확인'],
  ] as const).map(([key, label, value, setter, placeholder]) => <div key={key} className="space-y-2"><Label htmlFor={`${id}-${key}`}>{label}</Label><Textarea id={`${id}-${key}`} value={value} onChange={event => setter(event.target.value)} placeholder={placeholder} maxLength={6000} disabled={save.isPending} /></div>)}{watchError && <p role="alert" className="text-sm text-destructive">{watchError}</p>}{save.error && <p role="alert" className="text-sm text-destructive">{save.error.message} 입력한 내용은 유지됩니다.</p>}<Button type="submit" disabled={save.isPending || !reason.trim() || newerRecord || !!watchError}>{save.isPending && <LoaderCircle className="size-4 animate-spin" />}내 판단 v{baseRevision + 1} 저장</Button></form>
    <div className="space-y-3"><h3 className="text-sm font-medium">내 판단 이력</h3>{!item.notes.length && <p className="text-sm text-muted-foreground">아직 저장한 판단이 없습니다.</p>}{[...item.notes].sort((a, b) => b.revision - a.revision).map(note => <Fold key={note.id} title={`v${note.revision} · ${researchDate(note.created_at)}`}><NoteDetails note={note} /></Fold>)}</div>
  </div>
}

function Preparation({ run, onCancel, cancelling }: { run: ResearchRun; onCancel?: () => void; cancelling?: boolean }) {
  const active = ['queued', 'running'].includes(run.status)
  const items = run.preparation?.items ?? []
  if (!active && !items.length) return null
  const details = <ul className="grid gap-3 sm:grid-cols-2">{items.map(item => (
    <li key={item.id} className="min-w-0 space-y-1">
      <p className="flex items-start gap-2 text-sm">
        {['checking', 'collecting'].includes(item.status) && active ? <LoaderCircle className="mt-0.5 size-3.5 shrink-0 animate-spin" /> : ['available', 'collected'].includes(item.status) ? <Check className="mt-0.5 size-3.5 shrink-0 text-primary" /> : null}
        <span>{item.label} · <span className={item.status === 'failed' ? 'text-destructive' : 'text-muted-foreground'}>{!active && ['pending', 'checking', 'collecting'].includes(item.status) ? '준비 중단' : preparationStatus(item.status)}</span></span>
      </p>
      {item.detail && <p className="text-caption text-muted-foreground">{item.detail}</p>}
    </li>
  ))}</ul>
  return <div className="rounded-xl border bg-muted/30 p-4" aria-live="polite" aria-atomic="false">
    {active ? <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p role="status" className="flex items-center gap-2 text-sm font-medium"><LoaderCircle className="size-4 animate-spin" />{researchPhase(run.phase, run.status)}</p>
        {onCancel && <Button variant="ghost" size="sm" disabled={cancelling} onClick={onCancel}><Square className="size-3" />조사 취소</Button>}
      </div>
      <p className="mb-4 mt-1 text-caption text-muted-foreground">화면을 나가도 계속 진행됩니다. 준비된 자료부터 확인할 수 있습니다.</p>
      {details}
    </> : <Collapsible>
      <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="h-auto w-full justify-between gap-2 whitespace-normal px-0 text-left">자료 준비 기록 · 확보 {items.filter(item => ['available', 'collected'].includes(item.status)).length}/{items.length}<ChevronDown className="size-4 shrink-0" /></Button></CollapsibleTrigger>
      <CollapsibleContent className="pt-3">{details}</CollapsibleContent>
    </Collapsible>}
  </div>
}

function ResearchWorkspace({ item }: { item: DiscoveryCase }) {
  const id = useId()
  const [sp, setSp] = useSearchParams()
  const [question, setQuestion] = useState(item.question)
  const [asOf, setAsOf] = useState('')
  const [settings, setSettings] = useState(false)
  const [web, setWeb] = useState(true) // 웹 조사 레인(D-188)
  const selected = sp.get('research')
  const tab = ['answer', 'sources', 'judgment'].includes(sp.get('researchTab') ?? '') ? sp.get('researchTab')! : 'answer'
  const history = [...item.research_runs].sort((a, b) => b.created_at.localeCompare(a.created_at))
  const active = history.find(run => ['queued', 'running'].includes(run.status))
  const current = history.find(run => run.id === selected) ?? history[0]
  const start = useDiscoveryAction<ResearchRun>()
  const cancel = useDiscoveryAction<ResearchRun>()
  const busy = start.isPending || !!active
  const update = (key: string, value: string) => setSp(previous => { const next = new URLSearchParams(previous); next.set(key, value); return next }, { replace: true })
  async function research() {
    if (busy || !question.trim()) return
    try {
      const run = await start.mutateAsync({ path: `/cases/${item.id}/research`, body: { question: question.trim(), ...(asOf ? { as_of: asOf } : {}), web } })
      setSp(previous => { const next = new URLSearchParams(previous); next.set('research', run.id); next.set('researchTab', 'answer'); return next }, { replace: true })
      setSettings(false)
    } catch { /* Retain question/date and idempotency key for a deliberate retry. */ }
  }
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-section font-semibold">기업 조사</h2><p className="mt-1 text-caption text-muted-foreground">{current ? `${researchDate(current.created_at)} · 자료 기준 ${current.packet?.as_of ?? current.as_of ?? '준비 중'}` : '발견한 신호를 기업의 이야기와 연결합니다.'}</p></div>
      <Sheet open={settings} onOpenChange={setSettings}>
        <SheetTrigger asChild><Button variant="outline" size="sm"><Settings2 className="size-4" />{history.length ? '후속 조사·이력' : '조사 시작'}</Button></SheetTrigger>
        <SheetContent className="w-full! overflow-y-auto sm:max-w-lg!">
          <SheetHeader><SheetTitle>질문을 이어서 조사하기</SheetTitle><SheetDescription>필요한 기업 자료를 확인·수집하고 새 조사 기록을 만듭니다. 이전 조사와 판단은 그대로 남습니다.</SheetDescription></SheetHeader>
          <div className="space-y-6 px-6 pb-8">
            <form className="space-y-4" onSubmit={event => { event.preventDefault(); void research() }}>
              <div className="space-y-2"><Label htmlFor={`${id}-question`}>이번에 조사할 질문</Label><Textarea id={`${id}-question`} value={question} onChange={event => setQuestion(event.target.value)} maxLength={4000} disabled={busy} className="min-h-36" /></div>
              <div className="space-y-2"><Label htmlFor={`${id}-date`}>자료 기준일 · 선택</Label><Input id={`${id}-date`} type="date" value={asOf} onChange={event => setAsOf(event.target.value)} disabled={busy} /><p className="text-caption text-muted-foreground">비우면 현재 시점에서 조사합니다. 과거 기준일을 선택하면 신규 수집을 생략하고, 공개 시점을 확인할 수 있는 저장 자료를 사용합니다.</p></div>
              <label className="flex items-start gap-2 text-sm"><Checkbox checked={web} onCheckedChange={value => setWeb(value === true)} disabled={busy} aria-label="웹도 확인" className="mt-0.5" /><span>웹도 확인 — 사업보고서·IR·뉴스·리포트를 검색해 발췌를 확보합니다<span className="block text-caption text-muted-foreground">모델 1콜(최대 3분). 최근 24시간 안의 웹 조사가 있으면 재사용합니다.</span></span></label>
              {start.error && <p role="alert" className="text-sm text-destructive">{start.error.message}</p>}
              <Button type="submit" disabled={busy || !question.trim()}>{busy && <LoaderCircle className="size-4 animate-spin" />}{history.length ? '새 자료로 후속 조사' : '기업 조사 시작'}</Button>
            </form>
            {!!history.length && <div className="space-y-3 border-t pt-5"><Label htmlFor={`${id}-history`}><History className="size-4" />조사 이력</Label><Select value={current?.id} onValueChange={value => { update('research', value); setSettings(false) }}><SelectTrigger id={`${id}-history`} className="w-full"><SelectValue /></SelectTrigger><SelectContent>{history.map((run, index) => <SelectItem key={run.id} value={run.id}>#{history.length - index} · {researchDate(run.created_at)} · {researchStatus(run.status)}</SelectItem>)}</SelectContent></Select><p className="text-caption text-muted-foreground">당시 읽은 자료와 결과를 그대로 확인합니다.</p></div>}
          </div>
        </SheetContent>
      </Sheet>
    </div>
    {cancel.error && <p role="alert" className="text-sm text-destructive">{cancel.error.message}</p>}
    {active && <Preparation run={active} cancelling={cancel.isPending} onCancel={() => cancel.mutate({ path: `/cases/${item.id}/research/${active.id}/cancel`, body: {} })} />}
    <Tabs value={tab} onValueChange={value => update('researchTab', value)}>
      <TabsList aria-label="종목 조사와 판단" className="h-auto! max-w-full flex-wrap">
        <TabsTrigger value="answer">조사 결과</TabsTrigger>
        <TabsTrigger value="sources">읽은 자료 {current?.packet?.lanes.reduce((sum, lane) => sum + lane.items.length, 0) ?? 0}</TabsTrigger>
        <TabsTrigger value="judgment">내 판단 {item.notes.length ? `v${Math.max(...item.notes.map(note => note.revision))}` : ''}</TabsTrigger>
      </TabsList>
      <div className={`mt-5 grid min-w-0 items-start gap-6 ${tab !== 'judgment' ? 'xl:grid-cols-[minmax(0,1fr)_minmax(260px,320px)]' : ''}`}>
        <div className={`min-w-0 ${tab === 'judgment' ? 'hidden' : ''}`}>
          <TabsContent forceMount value="answer" className="mt-0 space-y-5 data-[state=inactive]:hidden">
            {!current ? <div className="rounded-xl border border-dashed p-5"><h3 className="font-medium">이 발견에서 조사를 시작해 보세요.</h3><p className="mt-2 text-sm text-muted-foreground">필요한 재무·공시를 준비하고 시장 담론과 실적의 근거를 연결합니다.</p><Button className="mt-4" onClick={() => setSettings(true)}>질문 확인하고 조사 시작</Button></div> : <>
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{researchStatus(current.status)}</Badge>{current.id !== history[0]?.id && <Badge variant="secondary">이전 조사 기록</Badge>}</div>
                {current.error && <p role="alert" className="text-sm text-destructive">{current.error}</p>}
                {['cancelled', 'interrupted', 'failed'].includes(current.status) && <div className="space-y-3 rounded-xl bg-muted/50 p-4"><p className="text-sm">이 조사는 완료되지 않았습니다. 확보한 자료는 아래에서 확인하고 새 조사로 이어갈 수 있습니다.</p><Button variant="outline" size="sm" disabled={busy} onClick={() => setSettings(true)}>다시 조사하기</Button></div>}
                {current.status === 'partial' && <p className="text-caption text-hypothesis">일부 자료를 확보하지 못했습니다. 확인한 근거와 남은 공백을 함께 표시합니다.</p>}
              </div>
              <ResearchAnswer run={current} />
              {['queued', 'running'].includes(current.status) && !current.result && <div className="space-y-3" aria-label="조사 결과를 준비하는 중"><Skeleton className="h-5 w-2/3" /><Skeleton className="h-20 w-full" /></div>}
              {!active && <Preparation run={current} />}
              <ResearchChanges run={current} history={history} />
              <Fold title="이번 조사의 질문"><p className="whitespace-pre-wrap text-sm">{current.question}</p></Fold>
            </>}
          </TabsContent>
          <TabsContent forceMount value="sources" className="mt-0 data-[state=inactive]:hidden">
            {current?.packet ? <ResearchPacket key={current.id} run={current} /> : <p className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground">{active ? '자료를 확인하고 있습니다. 읽은 자료가 준비되면 여기에 표시됩니다.' : '이 기록에는 읽은 자료 묶음이 없습니다. 후속 조사를 시작하면 필요한 자료부터 확인합니다.'}</p>}
          </TabsContent>
        </div>
        <TabsContent forceMount value="judgment" className={tab === 'judgment' ? 'mt-0 min-w-0' : 'mt-0 hidden min-w-0 xl:block'}>
          <Card><CardHeader><CardTitle>내 판단</CardTitle></CardHeader><CardContent><JudgmentForm key={item.id} item={item} /></CardContent></Card>
        </TabsContent>
      </div>
    </Tabs>
  </div>
}

function DiscoveryContext({ item }: { item: DiscoveryCase }) {
  const evidence = item.discovery.evidence && typeof item.discovery.evidence === 'object' ? item.discovery.evidence as { status?: string } : {}
  return <Card className="h-full"><CardContent className="space-y-3 pt-5">
    <div className="flex flex-wrap items-center gap-2"><Badge variant="secondary">발견한 이유</Badge><span className="text-caption text-muted-foreground">{item.discovery.as_of} 기준</span></div>
    <p className="line-clamp-3 text-sm leading-relaxed">{item.discovery.question}</p>
    {evidence.status === 'provisional' && <p className="text-caption text-hypothesis">잠정 후보 · 검증되지 않은 가격 조건이 있습니다.</p>}
    {!!item.discovery.unsupported_conditions?.length && <p className="text-caption text-hypothesis">평가하지 못한 요청 조건 {item.discovery.unsupported_conditions.length}개 · 발견 상세에서 확인하세요.</p>}
    {item.discovery.saved_strategy && <p className="text-caption text-muted-foreground">{item.discovery.saved_strategy.name} · v{item.discovery.saved_strategy.version}</p>}
    <Sheet><SheetTrigger asChild><Button variant="outline" size="sm">조건·계산 근거 보기</Button></SheetTrigger><SheetContent className="w-full! overflow-y-auto sm:max-w-xl!"><SheetHeader><SheetTitle>발견 당시의 조건과 근거</SheetTitle><SheetDescription>{item.name} · {item.discovery.as_of} 기준의 원본 검색을 보존합니다.</SheetDescription></SheetHeader><div className="space-y-5 px-6 pb-8">
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{item.discovery.question}</p>
      <AnalysisConditions spec={item.discovery.spec} priceAdjustment={discoveryPriceAdjustment(item.discovery.evidence)} />
      {item.discovery.counts && <p className="text-caption text-muted-foreground">검색 {formatNumber(item.discovery.counts.universe)}종목 · 통과 {formatNumber(item.discovery.counts.matched)}종목 · 판단 불가 {formatNumber(item.discovery.counts.excluded)}종목</p>}
      {!!item.discovery.unsupported_conditions?.length && <div className="space-y-2 text-sm text-hypothesis"><h3 className="font-medium">평가하지 못한 요청 조건</h3><ul className="list-disc space-y-1 pl-5">{item.discovery.unsupported_conditions.map((condition, index) => <li key={index}>{condition}</li>)}</ul></div>}
      {!!item.discovery.warnings?.length && <div className="space-y-2"><h3 className="text-sm font-medium">자료와 평가의 한계</h3><ul className="list-disc space-y-2 pl-5 text-caption text-muted-foreground">{item.discovery.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
      <DiscoveryEvidence value={item.discovery.evidence} />
    </div></SheetContent></Sheet>
  </CardContent></Card>
}

export function DiscoveryResearch({ caseId, stockCode, priceContext }: { caseId: string; stockCode: string; priceContext?: ReactNode }) {
  const query = useDiscoveryCase(caseId)
  const [sp] = useSearchParams()
  if (query.isPending) return <div aria-label="발견 기록을 불러오는 중" role="status"><Skeleton className="h-64 w-full" /></div>
  if (query.isError || !query.data) return <ErrorState message={query.error?.message ?? '발견 기록을 불러오지 못했습니다.'} onRetry={() => query.refetch()} />
  const item = query.data
  if (item.stock_code !== stockCode) return <ErrorState message="발견 기록의 종목이 현재 기업과 다릅니다." />
  const returnQuery = new URLSearchParams({ run: item.source_run_id, candidate: item.stock_code })
  return <section aria-label="발견에서 이어지는 기업 리서치" className="min-w-0 space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Button asChild variant="ghost" size="sm"><Link to={`/discover?${returnQuery}`}><ArrowLeft className="size-4" />후보 목록으로</Link></Button>
      <nav aria-label="기존 기업 자료 더 보기" className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm"><Link to={`/analyze/${stockCode}/summary`}><Building2 className="size-4" />기업 개요·차트</Link></Button>
        <Button asChild variant="ghost" size="sm"><Link to={`/analyze/${stockCode}/financials?${sp}`}>실적·사업</Link></Button>
        <Button asChild variant="ghost" size="sm"><Link to={`/analyze/${stockCode}/mentions?${sp}`}>시장·공시 자료</Link></Button>
      </nav>
    </div>
    <div className={`grid min-w-0 items-stretch gap-5 ${priceContext ? 'lg:grid-cols-[minmax(240px,0.8fr)_minmax(0,1.2fr)]' : ''}`}><DiscoveryContext item={item} />{priceContext && <div className="min-w-0">{priceContext}</div>}</div>
    <ResearchWorkspace key={item.id} item={item} />
    <nav aria-label="추가 자료 탐색" className="flex flex-wrap gap-2 border-t pt-4"><Button asChild variant="ghost" size="sm"><Link to="/follow/transcripts">컨퍼런스콜 자료</Link></Button><Button asChild variant="ghost" size="sm"><Link to="/follow/trade">수출입 통계</Link></Button></nav>
  </section>
}
