import { useId, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { BookmarkPlus, ChevronDown, Eye, LoaderCircle, Play, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { GroupPicker } from '@/components/follow/GroupPicker'
import { useAppendDefaultRules } from '@/hooks/useGroups'
import { ErrorState } from '@/components/shared/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useDiscoveryAction, useDiscoveryCases, useRecommendations, useSavedStrategies } from '@/hooks/useDiscovery'
import { AnalysisConditions } from '@/components/analysis/AnalysisConditions'
import type { AnalysisRun } from '@/components/analysis/types'
import type { DiscoveryRecommendation, SavedStrategy } from '@/components/analysis/discoveryTypes'

export function SaveDiscoveryStrategy({ run }: { run: AnalysisRun }) {
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState('new')
  const [name, setName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [policy, setPolicy] = useState<'latest' | 'fixed'>('latest')
  const id = useId()
  const strategies = useSavedStrategies()
  const save = useDiscoveryAction<SavedStrategy>()
  const selected = strategies.data?.items.find(item => item.id === target)
  async function submit() {
    if (save.isPending || !name.trim()) return
    try {
      const saved = await save.mutateAsync({ path: selected ? `/strategies/${selected.id}/versions` : '/strategies', body: { source_run_id: run.id, name: name.trim(), purpose: purpose.trim(), date_policy: policy, ...(selected ? { expected_version: selected.current_version } : {}) } })
      toast.success(`${saved.name} · 버전 ${saved.current_version} 저장`)
      setOpen(false)
    } catch { /* Keep the draft and request key for retry. */ }
  }
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><Button variant="outline" size="sm"><BookmarkPlus className="size-4" />검색 전략 저장</Button></DialogTrigger>
    <DialogContent className="max-h-[85vh] overflow-y-auto"><DialogHeader><DialogTitle>검증한 검색을 다시 사용하기</DialogTitle><DialogDescription>질문·조건·출처 실행을 버전으로 보존합니다. 기존 전략에 추가해도 이전 조건은 남습니다.</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={event => { event.preventDefault(); void submit() }}>
        <div className="space-y-2"><Label htmlFor={`${id}-target`}>저장 위치</Label><Select value={target} onValueChange={value => { setTarget(value); const item = strategies.data?.items.find(item => item.id === value); if (item) { setName(item.name); setPurpose(item.purpose) } }}><SelectTrigger id={`${id}-target`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="new">새 전략</SelectItem>{strategies.data?.items.map(item => <SelectItem key={item.id} value={item.id}>{item.name} · v{item.current_version}</SelectItem>)}</SelectContent></Select></div>
        {strategies.isError && <ErrorState message="기존 전략을 불러오지 못했습니다." onRetry={() => strategies.refetch()} />}
        <div className="space-y-2"><Label htmlFor={`${id}-name`}>전략 이름</Label><Input id={`${id}-name`} value={name} onChange={event => setName(event.target.value)} required maxLength={120} placeholder="추세를 유지하는 거래량 상위 종목" /></div>
        <div className="space-y-2"><Label htmlFor={`${id}-purpose`}>언제 사용할 검색인가요?</Label><Textarea id={`${id}-purpose`} value={purpose} onChange={event => setPurpose(event.target.value)} maxLength={2000} placeholder="강한 추세에서 눌림목 후보를 발견할 때" /></div>
        <div className="space-y-2"><Label htmlFor={`${id}-policy`}>재실행 기준일</Label><Select value={policy} onValueChange={value => setPolicy(value as 'latest' | 'fixed')}><SelectTrigger id={`${id}-policy`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="latest">실행할 때의 최신 보유일</SelectItem><SelectItem value="fixed">현재 기준일 고정 · {run.result?.as_of}</SelectItem></SelectContent></Select></div>
        {save.error && <p role="alert" className="text-sm text-destructive">{save.error.message}</p>}
        <Button type="submit" className="w-full" disabled={!name.trim() || save.isPending}>{save.isPending && <LoaderCircle className="size-4 animate-spin" />}{selected ? `버전 ${selected.current_version + 1} 저장` : '전략 저장'}</Button>
      </form>
    </DialogContent>
  </Dialog>
}

function SavedStrategyItem({ item, onOpen }: { item: SavedStrategy; onOpen: (id: string) => void }) {
  const [version, setVersion] = useState(String(item.current_version))
  const selected = item.versions.find(entry => entry.number === Number(version)) ?? item.versions.at(-1)!
  const run = useDiscoveryAction<AnalysisRun>()
  const append = useAppendDefaultRules()
  async function start() {
    if (run.isPending) return
    try { onOpen((await run.mutateAsync({ path: `/strategies/${item.id}/run`, body: { version: selected.number } })).id) } catch { /* Inline error. */ }
  }
  return <article className="min-w-0 space-y-3 rounded-lg border p-4">
    <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="font-medium">{selected.name ?? item.name}</h3><Badge variant="outline">{item.versions.length}개 버전</Badge></div>
    <p className="text-sm text-muted-foreground">{selected.purpose || item.purpose || '사용 목적을 아직 기록하지 않았습니다.'}</p>
    <div className="flex flex-wrap items-center gap-2"><Select value={String(selected.number)} onValueChange={setVersion}><SelectTrigger aria-label={`${item.name} 버전`} className="w-auto min-w-40"><SelectValue /></SelectTrigger><SelectContent>{[...item.versions].reverse().map(entry => <SelectItem key={entry.number} value={String(entry.number)}>v{entry.number} · {entry.created_at.slice(0, 10)}</SelectItem>)}</SelectContent></Select><p className="text-caption text-muted-foreground">{selected.date_policy === 'fixed' ? `기준일 고정 · ${selected.as_of ?? selected.spec.as_of ?? '원본 실행일'}` : '최신 보유일로 재실행'}</p></div>
    <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm">질문과 계산 조건 <ChevronDown className="size-3.5" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-3 pt-3"><p className="whitespace-pre-wrap text-sm">{selected.question}</p><AnalysisConditions spec={selected.spec} /><Link className="text-caption text-primary hover:underline" to={`/discover?run=${selected.source_run_id}`}>이 버전의 원본 분석 보기</Link></CollapsibleContent></Collapsible>
    {run.error && <p role="alert" className="text-sm text-destructive">{run.error.message}</p>}
    <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="secondary" disabled={run.isPending} onClick={() => void start()}>{run.isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />}v{selected.number} 실행</Button>
      {(selected.spec.strategy_conditions?.length ?? 0) > 0 && <GroupPicker label="이 조건으로 감시" variant="ghost" icon={<Eye className="size-4" />} busy={append.isPending} onPick={async id => { const detail = await append.mutateAsync({ groupId: id, rules: (selected.spec.strategy_conditions ?? []).map(condition => ({ strategy_id: condition.strategy_id, params: condition.params, within_days: condition.within_days, source_strategy_id: item.id, source_version: selected.number })) }); toast.success(`‘${detail.name}’ 기본 조건에 ${selected.spec.strategy_conditions!.length}개를 추가했습니다.`) }} />}
    </div>
  </article>
}

export function DiscoveryRecommendations({ onOpen, onAppend, runId, stockCode, compact = false }: { onOpen: (id: string) => void; onAppend?: (phrase: string) => void; runId?: string; stockCode?: string; compact?: boolean }) {
  const query = useRecommendations(runId, stockCode)
  const groups = useMemo(() => { const map = new Map<string | undefined, DiscoveryRecommendation[]>(); for (const item of query.data?.items ?? []) map.set(item.group, [...(map.get(item.group) ?? []), item]); return [...map.entries()] }, [query.data])
  const run = useDiscoveryAction<AnalysisRun>()
  async function start(id: string) {
    if (run.isPending) return
    try { onOpen((await run.mutateAsync({ path: `/recommendations/${encodeURIComponent(id)}/run`, body: { ...(runId && stockCode ? { run_id: runId, stock_code: stockCode } : {}) } })).id) } catch { /* Inline error. */ }
  }
  return <div className="space-y-3">
    <p className="text-caption text-muted-foreground">{stockCode ? '이 종목에서 검증된 신호와 목적별 예시입니다. 조건을 확인하고 직접 실행해 보세요.' : onAppend ? '누르면 위 질문에 조건이 한 줄씩 추가됩니다. 여러 개를 조합한 뒤 검색하세요. 수익률 순위에 따른 추천은 아닙니다.' : '찾고 싶은 기회와 가용 자료를 기준으로 고른 검색 예시입니다. 수익률 순위에 따른 추천은 아닙니다.'}</p>
    {query.isPending && <Skeleton className="h-28 w-full" />}
    {query.isError && <ErrorState message="검색 제안을 불러오지 못했습니다." onRetry={() => query.refetch()} />}
    {query.data?.items.length === 0 && <p className="text-sm text-muted-foreground">현재 제안할 수 있는 검색이 없습니다.</p>}
    {groups.map(([group, items]) => <section key={group ?? 'all'} aria-label={group ?? '검색 제안'} className="space-y-2">{group && groups.length > 1 && <h3 className="text-caption font-medium text-muted-foreground">{group}</h3>}<div className={compact ? 'grid grid-cols-1 gap-3 sm:grid-cols-2' : 'grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3'}>{items.map(item => <article key={item.id} className="flex min-w-0 flex-col gap-3 rounded-xl bg-card p-4 ring-1 ring-border/50"><div className="space-y-1"><h4 className="font-medium">{item.name}</h4><p className="text-sm text-muted-foreground">{item.purpose}</p></div><Collapsible className="mt-auto"><div className="flex flex-wrap items-center justify-between gap-2"><CollapsibleTrigger asChild><Button variant="ghost" size="sm">조건·자료<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger>{onAppend && item.phrase ? <Button size="sm" variant="outline" onClick={() => onAppend(item.phrase!)} aria-label={`${item.name} 조건을 질문에 추가`}><Plus className="size-3.5" />조건 추가</Button> : <Button size="sm" variant="outline" disabled={run.isPending} onClick={() => void start(item.id)}>{run.isPending && <LoaderCircle className="size-3.5 animate-spin" />}이 조건으로 검색</Button>}</div><CollapsibleContent className="space-y-3 pt-3"><p className="text-sm text-muted-foreground">{item.reason}</p><AnalysisConditions spec={item.spec} /><p className="whitespace-pre-wrap break-words text-caption text-muted-foreground">자료: {typeof item.availability === 'string' ? item.availability : JSON.stringify(item.availability)}</p>{item.limitations.map((text, index) => <p key={index} className="text-caption text-muted-foreground">{text}</p>)}</CollapsibleContent></Collapsible></article>)}</div></section>)}
    {run.error && <p role="alert" className="text-sm text-destructive">{run.error.message}</p>}
  </div>
}

export function DiscoveryLibrary({ onOpen }: { onOpen: (id: string) => void }) {
  const [params, setParams] = useSearchParams()
  const requestedTab = params.get('library')
  const tab = requestedTab === 'recommendations' || requestedTab === 'cases' ? requestedTab : 'strategies'
  const strategies = useSavedStrategies()
  const cases = useDiscoveryCases()
  return <Card><CardHeader><CardTitle className="text-card-title">나의 검색과 리서치</CardTitle><p className="text-sm text-muted-foreground">유용했던 조건을 다시 실행하고, 발견한 종목의 근거와 판단을 이어서 살펴보세요.</p></CardHeader><CardContent>
    <Tabs value={tab} onValueChange={value => setParams(previous => { const next = new URLSearchParams(previous); next.set('library', value); return next }, { replace: true })}><TabsList className="max-w-full" aria-label="발견 라이브러리"><TabsTrigger value="strategies">저장 전략</TabsTrigger><TabsTrigger value="recommendations">검색 제안</TabsTrigger><TabsTrigger value="cases">조사 기록</TabsTrigger></TabsList>
      <TabsContent value="strategies" className="space-y-3 pt-3">{strategies.isPending && <Skeleton className="h-24 w-full" />}{strategies.isError && <ErrorState message="저장 전략을 불러오지 못했습니다." onRetry={() => strategies.refetch()} />}{strategies.data?.items.length === 0 && <p className="py-4 text-sm text-muted-foreground">아직 저장한 전략이 없습니다. 검색 결과에서 ‘검색 전략 저장’을 누르면 조건을 다시 사용할 수 있습니다.</p>}{strategies.data?.items.map(item => <SavedStrategyItem key={`${item.id}-${item.current_version}`} item={item} onOpen={onOpen} />)}</TabsContent>
      <TabsContent value="recommendations" className="pt-3"><DiscoveryRecommendations compact onOpen={onOpen} /></TabsContent>
      <TabsContent value="cases" className="space-y-3 pt-3">{cases.isPending && <Skeleton className="h-24 w-full" />}{cases.isError && <ErrorState message="조사 기록을 불러오지 못했습니다." onRetry={() => cases.refetch()} />}{cases.data?.items.length === 0 && <p className="py-4 text-sm text-muted-foreground">검색 결과의 ‘기업 조사’로 발견 맥락을 보존하고 리서치를 시작할 수 있습니다.</p>}{cases.data?.items.map(item => <Link key={item.id} to={`/analyze/${item.stock_code}/summary?discovery=${item.id}`} className="block space-y-1 rounded-lg border p-4 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"><span className="font-medium">{item.name} <span className="text-caption text-muted-foreground">{item.stock_code} · {item.discovery.as_of}</span></span><p className="line-clamp-2 text-sm text-muted-foreground">{item.question}</p><p className="text-caption text-muted-foreground">조사 {item.research_runs.length}회 · 판단 기록 {item.notes.length}회</p></Link>)}</TabsContent>
    </Tabs>
  </CardContent></Card>
}
