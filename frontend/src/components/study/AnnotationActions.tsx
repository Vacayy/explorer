import { useState } from 'react'
import { ChevronDown, Send } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Markdown } from '@/components/shared/Markdown'
import { citationComponents, linkifyCitations } from '@/components/chat/citations'
import { INTENTS, intentLabel } from '@/components/study/StudyPalette'
import { ResearchResults } from '@/components/study/ResearchResults'
import { errorMessage, type Annotation } from '@/components/study/useStudy'
import type { StudyActionsController } from '@/hooks/useStudyActions'
import type { StudyAction, StudyActionRequest, StudyIntent } from '@/types'

function statusLabel(action: StudyAction) {
  return action.status === 'queued' ? `대기 ${action.queue_position || 1}번째` :
    action.status === 'running' ? '답변 중' : action.status === 'complete' ? '답변 완료' : action.status === 'error' ? '다시 시도 가능' : '취소됨'
}
function age(time: string) { return Date.now() - Date.parse(time.replace(' ', 'T') + 'Z') }

export function AnnotationActions({ annotation, controller, disabled, expanded, onExpand, onAdopt }: {
  annotation: Annotation; controller: StudyActionsController; disabled: boolean;
  expanded: boolean; onExpand: (value: boolean) => void; onAdopt: (text: string) => void;
}) {
  const actions = controller.data?.filter(a => a.annotation_id === annotation.id) ?? []
  const [viewedId, setViewedId] = useState<number | null>(null)
  const [drafts, setDrafts] = useState<Record<number, string>>({}), [busy, setBusy] = useState(false)
  const selected = actions.find(a => a.id === viewedId) ?? actions.at(-1)
  const question = drafts[selected?.id ?? 0] ?? ''
  function setQuestion(value: string) { if (selected) setDrafts(previous => ({ ...previous, [selected.id]: value })) }
  const annotationRef = { id: annotation.id, revision: annotation.revision }
  async function submit(intent: StudyIntent, extra: Partial<StudyActionRequest> = {}) {
    setBusy(true)
    try {
      const result = await controller.submit({ intent, annotation: annotationRef, ...extra })
      setViewedId(result.id); onExpand(true)
      if (extra.parent_id) setQuestion('')
    } catch (e) { toast.error(errorMessage(e)) } finally { setBusy(false) }
  }
  async function command(id: number | null, name: 'cancel' | 'recover' | 'resume') {
    setBusy(true)
    try { await controller.command(id, name) } catch (e) { toast.error(errorMessage(e)) } finally { setBusy(false) }
  }
  const disabledAction = disabled || busy
  return <div className="study-annotation-actions">
    <div className="flex flex-wrap gap-1" aria-label={`주석 ${annotation.id} AI 도구`}>
      {INTENTS.map(({ key, label, Icon }) => <Button key={key} size="xs" variant="ghost" disabled={disabledAction} onClick={() => submit(key)}><Icon aria-hidden="true" />{label}</Button>)}
    </div>
    {!!actions.length && <Collapsible open={expanded} onOpenChange={onExpand} className="mt-2">
      <CollapsibleTrigger asChild><Button variant="secondary" size="sm" className="w-full justify-between" aria-label={`주석 ${annotation.id} AI 답변`}>
        <span>AI · {selected ? intentLabel(selected.intent) : '답변'} <span className="font-normal">{selected && statusLabel(selected)}</span></span><ChevronDown aria-hidden="true" />
      </Button></CollapsibleTrigger>
      <CollapsibleContent className="pt-3 space-y-3">
        {actions.length > 1 && <div className="flex flex-wrap gap-1" aria-label="이 표시의 답변 이력">{actions.map((a, i) => <Button key={a.id} size="xs" variant={a.id === selected?.id ? 'secondary' : 'ghost'} aria-pressed={a.id === selected?.id} onClick={() => setViewedId(a.id)}>{i + 1}. {a.parent_id ? '후속 질문' : intentLabel(a.intent)}</Button>)}</div>}
        {selected && <>
          {selected.parent_id && <p className="text-sm rounded-lg bg-muted p-2">{selected.question}</p>}
          {selected.annotation_revision !== annotation.revision && <p className="text-caption text-muted-foreground">요청 당시 저장된 코멘트를 기준으로 한 답변입니다.</p>}
          {(selected.status === 'queued' || selected.status === 'running') && <div role="status" className="text-sm text-muted-foreground">
            {selected.status === 'queued' ? `순서대로 답변합니다 · ${statusLabel(selected)}` : '문맥을 읽고 필요한 근거를 확인하고 있습니다.'}
            <p className="text-caption mt-1">다른 부분을 계속 읽고 표시할 수 있습니다.</p>
          </div>}
          {selected.status === 'queued' && <div className="flex gap-2"><Button size="xs" variant="outline" disabled={busy} onClick={() => command(selected.id, 'cancel')}>요청 취소</Button>{age(selected.created_at) > 30000 && <Button size="xs" variant="ghost" disabled={busy} onClick={() => command(null, 'resume')}>대기열 이어서 실행</Button>}</div>}
          {selected.status === 'running' && selected.started_at && age(selected.started_at) > 600000 && <Button size="xs" variant="outline" disabled={busy} onClick={() => command(selected.id, 'recover')}>멈춘 요청 정리</Button>}
          {(selected.status === 'error' || selected.status === 'cancelled') && <div>
            <p className="text-sm text-muted-foreground" role={selected.status === 'error' ? 'alert' : undefined}>{selected.error || '요청을 취소했습니다. 표시는 남아 있습니다.'}</p>
            <Button className="mt-2" size="xs" variant="outline" disabled={disabledAction} onClick={() => submit(selected.intent, { retry_of: selected.id })}>같은 요청 다시 시도</Button>
          </div>}
          {selected.status === 'complete' && selected.result?.answer && <div className="study-action-answer">
            <Markdown components={citationComponents(selected.result.citations ?? null)}>{linkifyCitations(selected.result.answer, selected.result.citations ?? null)}</Markdown>
            {!!selected.result.research?.notes?.length && <p className="text-caption text-muted-foreground mt-2">{[...new Set(selected.result.research.notes)].join(' ')}</p>}
            <ResearchResults research={selected.result.research} excerpts={selected.intent==='related'} preferredHrefs={(selected.result.citations??[]).map(c=>c.href).filter((href):href is string=>!!href)} />
            <div className="flex flex-wrap gap-2 my-3">
              <Button size="xs" variant="outline" onClick={() => onAdopt(selected.result!.answer!)}>내 코멘트로 가져오기</Button>
              {selected.intent === 'related' && <Button size="xs" variant="outline" disabled={disabledAction} onClick={() => submit('related', { research: 'web' })}>웹으로 더 찾기</Button>}
            </div>
            <label className="text-caption text-muted-foreground" htmlFor={`action-followup-${annotation.id}`}>이 답변에 이어서 질문</label>
            <Textarea id={`action-followup-${annotation.id}`} value={question} onChange={e => setQuestion(e.target.value)} maxLength={4000} placeholder="이 부분은 왜 그런가요?" className="mt-1" onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && question.trim() && !disabledAction) { e.preventDefault(); void submit(selected.intent, { parent_id: selected.id, question }) } }} />
            <Button className="mt-2" size="sm" variant="outline" disabled={disabledAction || !question.trim()} onClick={() => submit(selected.intent, { parent_id: selected.id, question })}><Send aria-hidden="true" />이어서 질문</Button>
          </div>}
        </>}
      </CollapsibleContent>
    </Collapsible>}
  </div>
}
