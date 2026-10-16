import { useId } from 'react'
import { useSessionDraft } from '@/hooks/useSessionDraft'
import { isFollowupDraft, recoveryScope } from '@/components/analysis/discoveryDraft'
import { ArrowRight, ChevronDown, LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

export interface FollowupSubmission { question: string; parent_run_id: string; scope: 'universe' | 'candidates'; date_policy: 'same' | 'latest' }

export function DiscoveryFollowup({ runId, empty, busy, onSubmit }: { runId: string; empty: boolean; busy: boolean; onSubmit: (body: FollowupSubmission) => Promise<void> }) {
  const id = useId()
  const [draft, setDraft, stored] = useSessionDraft(`explorer:discovery:followup:v1:${runId}`, { question: '', scope: empty ? 'universe' as const : 'candidates' as const, policy: 'same' as const }, isFollowupDraft)
  const { question, policy } = draft
  const scope = recoveryScope(empty, draft.scope)
  const setQuestion = (question: string) => setDraft(previous => ({ ...previous, question }))
  const setScope = (scope: typeof draft.scope) => setDraft(previous => ({ ...previous, scope }))
  const setPolicy = (policy: typeof draft.policy) => setDraft(previous => ({ ...previous, policy }))
  const submit = () => { if (question.trim() && !busy) void onSubmit({ question: question.trim(), parent_run_id: runId, scope, date_policy: policy }) }
  return <section aria-label="이 검색에서 이어서 찾기" className="rounded-xl bg-card p-4">
    <form className="space-y-2" onSubmit={event => { event.preventDefault(); submit() }}>
      <div className="flex flex-wrap items-end gap-2"><div className="min-w-0 flex-1 basis-64 space-y-2"><Label htmlFor="discovery-followup-question">{empty ? '조건을 완화해서 다시 찾아보세요' : '조건을 바꾸거나 더 좁혀보세요'}</Label><Textarea id="discovery-followup-question" rows={2} className="min-h-16 resize-y" value={question} onChange={event => setQuestion(event.target.value)} disabled={busy} maxLength={12000} placeholder={empty ? '예: 최소 시가총액을 1,000억원으로 낮춰줘' : '예: 여기서 거래량이 증가한 종목만 보여줘'} onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) { event.preventDefault(); submit() } }} /></div><Button type="submit" disabled={busy || !question.trim()}>{busy ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}이어서 검색</Button></div>
      {empty && <p className="text-sm text-muted-foreground">통과 후보가 없어 이전 검색 대상 전체에서 다시 찾습니다. 변경할 조건을 적고 실행해 주세요.</p>}
      <Collapsible defaultOpen={empty}><CollapsibleTrigger asChild><Button type="button" variant="ghost" size="sm" className="h-auto py-1 text-caption text-muted-foreground">{scope === 'candidates' ? '현재 후보 안에서' : '이전 검색 대상 전체에서'} · {policy === 'same' ? '동일한 데이터' : '최신 보유 데이터'}<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-3 pt-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor={`${id}-scope`}>검색 범위</Label><Select value={scope} onValueChange={value => setScope(value as typeof scope)} disabled={busy}><SelectTrigger id={`${id}-scope`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="candidates" disabled={empty}>이전 통과 종목만</SelectItem><SelectItem value="universe">이전 검색 대상 전체</SelectItem></SelectContent></Select></div><div className="space-y-2"><Label htmlFor={`${id}-date`}>자료 기준</Label><Select value={policy} onValueChange={value => setPolicy(value as typeof policy)} disabled={busy}><SelectTrigger id={`${id}-date`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="same">이전과 동일한 데이터</SelectItem><SelectItem value="latest">최신 보유일 데이터</SelectItem></SelectContent></Select></div></div>
        <p className="text-caption text-muted-foreground">이전 조건을 유지하면서 변경하며, 새 실행으로 남깁니다. 이전 결과도 보존됩니다.</p>
      </CollapsibleContent></Collapsible>
      <p className="text-caption text-muted-foreground">{stored === false ? '이 브라우저에서 초안을 보존하지 못했습니다.' : '후속 질문과 범위는 이 탭에서 자동 보존됩니다.'}</p>
    </form>
  </section>
}
