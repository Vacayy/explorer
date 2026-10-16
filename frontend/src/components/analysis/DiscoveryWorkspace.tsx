import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { useAnalysisStrategies } from '@/hooks/useAnalysisStrategies'
import { useSessionDraft } from '@/hooks/useSessionDraft'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Skeleton } from '@/components/ui/skeleton'
import { activeConditions, ConditionPalette, ConditionStack, EMPTY_STACK, stackSubmission, type StrategySubmission } from '@/components/analysis/ConditionStackBuilder'
import { conditionInputError, conditionSignature, isPurposeDraft, type PurposeDraft } from '@/components/analysis/discoveryDraft'
import { isTerminal } from '@/components/analysis/events'
import type { AnalysisRun, AnalysisSpec } from '@/components/analysis/types'

const DESKTOP = '(min-width: 1024px)'

function useDesktop() {
  return useSyncExternalStore(
    notify => { const query = window.matchMedia(DESKTOP); query.addEventListener('change', notify); return () => query.removeEventListener('change', notify) },
    () => window.matchMedia(DESKTOP).matches)
}

/** 검색 대상까지 포함한 조합 서명 — 같으면 다시 검색하지 않는다. */
const draftSignature = (draft: PurposeDraft) => `${conditionSignature(activeConditions(draft))}|${draft.market}|${Number(draft.minimumCap)}|${draft.asOf}`
const specSignature = (spec: AnalysisSpec) => `${conditionSignature(spec.strategy_conditions ?? [])}|${spec.market}|${spec.min_market_cap / 100_000_000}|${spec.as_of ?? ''}`
const workspaceSpec = (spec: AnalysisSpec | null | undefined): spec is AnalysisSpec => !!spec && spec.mode === 'catalog' && !spec.expression && !!spec.strategy_conditions?.length

/**
 * 종목 발견 워크스페이스(D-224) — 좌: 조건 목록 · 중: 내 조건 스택 · 우: 결과.
 * 검색 버튼을 누르면 spec 명시 경로로 찾는다(모델 0, D-225 — 블록 변경마다 자동 실행하지 않음). 실행은 URL `run`이 소유하고,
 * 스택은 이 탭의 초안(sessionStorage)이 소유한다. 다른 경로(이전 검색·문장 검색)로 연 실행은 스택에 불러온다.
 */
export function DiscoveryWorkspace({ run, runLoading, startPending, onStart, results }: {
  run: AnalysisRun | undefined; runLoading: boolean; startPending: boolean
  onStart: (body: StrategySubmission) => Promise<void>; results: ReactNode
}) {
  const desktop = useDesktop()
  const catalog = useAnalysisStrategies()
  const definitions = catalog.data?.items ?? []
  const [draft, setDraft, stored] = useSessionDraft('explorer:discovery:stack:v1', EMPTY_STACK, isPurposeDraft)
  const submitted = useRef<string | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const busy = !!run && !isTerminal(run.status)
  const computing = busy || startPending
  const active = activeConditions(draft)
  const invalid = active.map(c => { const d = definitions.find(x => x.id === c.strategy_id); return d ? conditionInputError(c, d) : null }).find(Boolean)
  const missing = active.some(c => !definitions.some(d => d.id === c.strategy_id))
  const signature = draftSignature(draft)
  const runSpec = workspaceSpec(run?.spec) ? run!.spec! : null
  const current = runSpec ? specSignature(runSpec) : null
  const ready = !!catalog.data && !!active.length && !invalid && !missing

  // 다른 경로로 연 실행이면 그 조건을 스택에 불러온다(이 화면이 방금 보낸 조합이면 그대로 둔다).
  useEffect(() => {
    if (!runSpec || !current) return
    if (current === submitted.current) { submitted.current = null; return }
    if (current === signature) return
    setDraft({ conditions: runSpec.strategy_conditions ?? [], market: runSpec.market, minimumCap: String(runSpec.min_market_cap / 100_000_000), asOf: runSpec.as_of ?? '', off: [] })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 실행이 바뀔 때만 동기화
  }, [run?.id, current])

  function runNow() {
    if (!ready || computing || runLoading) return
    submitted.current = signature
    void onStart(stackSubmission(draft, definitions))
  }

  const status = !catalog.data ? '' : computing ? '결과를 계산하고 있습니다…'
    : invalid ? invalid : !active.length ? '켜 둔 조건이 없습니다.'
    : signature === current ? '결과가 지금 조건과 같습니다. 자료가 갱신됐으면 다시 검색해 최신으로 찾을 수 있습니다.'
    : stored === false ? '이 브라우저에 초안을 보존하지 못했습니다.' : current ? '조건이 바뀌었습니다. 검색을 누르면 다시 찾습니다.' : '조건을 쌓고 검색을 누르세요.'

  const palette = catalog.isPending ? <Skeleton className="h-80 w-full" aria-label="계산 조건 불러오는 중" />
    : catalog.isError ? <ErrorState message="계산 조건을 불러오지 못했습니다." onRetry={() => catalog.refetch()} />
    : <ConditionPalette draft={draft} definitions={definitions} busy={startPending} onChange={setDraft} />
  const stack = catalog.data ? <ConditionStack draft={draft} definitions={definitions} busy={startPending} computing={computing}
    result={runSpec ? run!.result ?? null : null} resultConditions={(runSpec?.strategy_conditions ?? []).map(c => c.strategy_id)} status={status}
    onChange={setDraft} onRunNow={runNow} runDisabled={!ready || computing || runLoading} /> : <Skeleton className="h-64 w-full" />

  if (!desktop) return <div className="min-w-0 space-y-4">
    <Collapsible open={paletteOpen} onOpenChange={setPaletteOpen} className="rounded-xl border bg-card">
      <CollapsibleTrigger asChild><Button variant="ghost" className="min-h-11 w-full justify-between">조건 목록·빠른 시작<ChevronDown className="size-4" /></Button></CollapsibleTrigger>
      <CollapsibleContent className="max-h-[60vh] overflow-y-auto border-t p-3">{palette}</CollapsibleContent>
    </Collapsible>
    <section aria-label="내 조건" className="@container rounded-xl border bg-card p-3">{stack}</section>
    <section aria-label="결과" className="min-w-0">{results}</section>
  </div>

  return <ResizablePanelGroup orientation="horizontal" className="min-h-[36rem] flex-1 rounded-xl border bg-card">
    <ResizablePanel defaultSize="22%" minSize="16%"><div aria-label="조건 목록 패널" className="h-full overflow-y-auto overscroll-contain p-3">{palette}</div></ResizablePanel>
    <ResizableHandle withHandle />
    <ResizablePanel defaultSize="30%" minSize="22%"><div aria-label="내 조건 패널" className="@container h-full overflow-y-auto overscroll-contain p-3">{stack}</div></ResizablePanel>
    <ResizableHandle withHandle />
    <ResizablePanel defaultSize="48%" minSize="30%"><div aria-label="결과 패널" className="h-full overflow-y-auto overscroll-contain p-3">{results}</div></ResizablePanel>
  </ResizablePanelGroup>
}
