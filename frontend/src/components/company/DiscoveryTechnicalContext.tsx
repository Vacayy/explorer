import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ChevronDown } from 'lucide-react'
import { useAnalysisRun } from '@/hooks/useMarketAnalysis'
import { comparisonCodes } from '@/components/analysis/discoveryDraft'
import { CandidateChart } from '@/components/analysis/AnalysisResults'
import { AnalysisConditions } from '@/components/analysis/AnalysisConditions'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { formatNumber, formatRelativeTime } from '@/utils/format'

export function DiscoveryTechnicalContext({ runId, code, original, latest, onView, currentUnavailable }: {
  runId: string; code: string; original: boolean; latest?: string; onView?: (original: boolean) => void; currentUnavailable?: string
}) {
  const [params] = useSearchParams()
  const query = useAnalysisRun(runId)
  const run = query.data
  const result = run?.result
  const candidate = result?.items.find(item => item.code === code)
  const back = new URLSearchParams({ run: runId, candidate: code })
  const compared = comparisonCodes(params.get('source_compare'), result?.items.map(item => item.code) ?? [])
  if (compared.length) back.set('compare', compared.join(','))
  if (params.get('source_sort')) back.set('sort', params.get('source_sort') === 'cap_asc' ? 'cap_asc' : 'cap_desc')
  return <section aria-label="발견 맥락" className="space-y-4">
    <div className="space-y-3 rounded-xl bg-muted/40 p-4">
      <Button variant="ghost" size="sm" className="h-auto whitespace-normal px-0" asChild><Link to={`/discover?${back}`}><ArrowLeft className="size-4" />발견 후보 목록으로</Link></Button>
      {query.isPending && <Skeleton className="h-12 w-full" aria-label="발견 맥락 불러오는 중" />}
      {query.isError && <ErrorState message="발견 당시 검색을 불러오지 못했습니다." onRetry={() => query.refetch()} />}
      {run && <>
        <p className="whitespace-pre-wrap text-sm font-medium">{run.question}</p>
        <p className="text-caption text-muted-foreground">발견 시세 기준 {result?.as_of ?? '미확인'} · 검색 실행 {formatRelativeTime(run.created_at)}</p>
        {result && <>
          {result.counts.excluded > 0 && <p className="text-caption text-muted-foreground">원 검색 대상 {formatNumber(result.counts.universe)}개 중 미평가 {formatNumber(result.counts.excluded)}개 · 자료 부족이나 계산 오류는 조건 탈락과 구분합니다.</p>}
          {!!result.unsupported_conditions?.length && <p className="text-sm text-hypothesis">평가하지 못한 요청 조건: {result.unsupported_conditions.join(' · ')}</p>}
          <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="px-0">발견 당시 조건·검색 범위<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-3 pt-2"><AnalysisConditions spec={result.spec} definitions={result.strategy_definitions} priceAdjustment={run.snapshot?.price_adjustment?.status} />
            {!!result.warnings.length && <ul className="list-disc space-y-1 pl-5 text-caption text-muted-foreground">{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
          </CollapsibleContent></Collapsible>
        </>}
      </>}
      <ToggleGroup type="single" variant="outline" value={original ? 'original' : 'latest'} onValueChange={value => { if (value) onView?.(value === 'original') }} aria-label="분석 시점" className="flex-wrap justify-start">
        <ToggleGroupItem value="original" className="h-auto min-h-11 whitespace-normal py-2">발견 당시{result?.as_of ? ` · ${result.as_of}` : ''}</ToggleGroupItem>
        <ToggleGroupItem value="latest" disabled={!!currentUnavailable || !onView} className="h-auto min-h-11 whitespace-normal py-2">현재 기술적 분석{latest ? ` · ${latest}` : ''}</ToggleGroupItem>
      </ToggleGroup>
      {currentUnavailable && <p className="text-sm text-muted-foreground">{currentUnavailable}</p>}
      <p className="text-caption text-muted-foreground">{original ? '당시 검색에 저장된 차트와 조건 판정입니다.' : '현재 보유 시세에 기본 분석 조건을 적용합니다. 발견 당시 조건과 매개변수가 다를 수 있습니다.'}</p>
    </div>
    {original && result && candidate && <CandidateChart key={`${runId}:${code}`} runId={runId} candidate={candidate} asOf={result.as_of} maPeriod={result.spec.ma_period} catalog={result.spec.mode === 'catalog'} definitions={result.strategy_definitions} showActions={false} />}
    {original && run && !candidate && <p role="status" className="rounded-xl border p-4 text-sm">이 검색에서 해당 종목의 저장된 판정을 찾지 못했습니다. 후보 목록에서 다시 선택하거나 현재 기술적 분석으로 전환해 주세요.</p>}
  </section>
}
