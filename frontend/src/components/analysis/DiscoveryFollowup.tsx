import { useId, useState } from 'react'
import { ArrowRight, ChevronDown, LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

export interface FollowupSubmission { question: string; parent_run_id: string; scope: 'universe' | 'candidates'; date_policy: 'same' | 'latest' }

export function DiscoveryFollowup({ runId, busy, onSubmit }: { runId: string; busy: boolean; onSubmit: (body: FollowupSubmission) => Promise<void> }) {
  const id = useId()
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState<'universe' | 'candidates'>('candidates')
  const [policy, setPolicy] = useState<'same' | 'latest'>('same')
  const submit = () => { if (question.trim() && !busy) void onSubmit({ question: question.trim(), parent_run_id: runId, scope, date_policy: policy }) }
  return <section aria-label="이 검색에서 이어서 찾기" className="rounded-xl bg-card p-4">
    <form className="space-y-2" onSubmit={event => { event.preventDefault(); submit() }}>
      <div className="flex flex-wrap items-end gap-2"><div className="min-w-0 flex-1 basis-64 space-y-2"><Label htmlFor={`${id}-question`}>조건을 바꾸거나 더 좁혀보세요</Label><Textarea id={`${id}-question`} rows={2} className="min-h-16 resize-y" value={question} onChange={event => setQuestion(event.target.value)} disabled={busy} maxLength={12000} placeholder="예: 여기서 거래량이 증가한 종목만 보여줘" onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) { event.preventDefault(); submit() } }} /></div><Button type="submit" disabled={busy || !question.trim()}>{busy ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}이어서 검색</Button></div>
      <Collapsible><CollapsibleTrigger asChild><Button type="button" variant="ghost" size="sm" className="h-auto py-1 text-caption text-muted-foreground">{scope === 'candidates' ? '현재 후보 안에서' : '이전 검색 대상 전체에서'} · {policy === 'same' ? '동일한 데이터' : '최신 보유 데이터'}<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger><CollapsibleContent className="space-y-3 pt-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor={`${id}-scope`}>검색 범위</Label><Select value={scope} onValueChange={value => setScope(value as typeof scope)} disabled={busy}><SelectTrigger id={`${id}-scope`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="candidates">이전 통과 종목만</SelectItem><SelectItem value="universe">이전 검색 대상 전체</SelectItem></SelectContent></Select></div><div className="space-y-2"><Label htmlFor={`${id}-date`}>자료 기준</Label><Select value={policy} onValueChange={value => setPolicy(value as typeof policy)} disabled={busy}><SelectTrigger id={`${id}-date`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="same">이전과 동일한 데이터</SelectItem><SelectItem value="latest">최신 보유일 데이터</SelectItem></SelectContent></Select></div></div>
        <p className="text-caption text-muted-foreground">이전 조건을 유지하면서 변경하며, 새 실행으로 남깁니다. 이전 결과도 보존됩니다.</p>
      </CollapsibleContent></Collapsible>
    </form>
  </section>
}
