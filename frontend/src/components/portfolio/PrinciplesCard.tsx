import { useState } from 'react'
import { ChevronDown, LoaderCircle, Pencil, Trash2, Wand2, X } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/shared/ErrorState'
import { useDeletePrinciple, useParsePrinciple, usePortfolioPrinciples, useReplacePrinciple, useSavePrinciple, useUpdatePrincipleText } from '@/hooks/usePortfolio'
import type { PortfolioPrinciple, PrincipleParse } from '@/types'

/**
 * 운용 원칙(D-227·D-228) — 자연어로 적으면 모델이 한 번 풀어 ① 기계가 점검할 수치 규칙 ② 대화에서 참고할 원칙 목록으로
 * 나눠 보여 주고, 사용자가 확인한 그대로 저장한다. ①은 어긴 순간 텔레그램으로만 알리고, ②와 원문은 대화가 판단 기준으로 읽는다.
 * 원문은 로컬 DB에만.
 */
export function PrinciplesCard() {
  const list = usePortfolioPrinciples()
  const parse = useParsePrinciple()
  const save = useSavePrinciple()
  const remove = useDeletePrinciple()
  const [text, setText] = useState('')
  const [preview, setPreview] = useState<PrincipleParse | null>(null)
  const busy = parse.isPending || save.isPending

  function run() {
    if (text.trim().length < 3 || busy) return
    parse.mutate(text.trim(), { onSuccess: setPreview, onError: e => toast.error(e.message) })
  }
  function confirm() {
    if (!preview) return
    save.mutate({ text: text.trim(), rules: preview.rules, notes: preview.unparsed }, {
      onSuccess: () => { setText(''); setPreview(null); toast.success('원칙을 저장했습니다.') },
      onError: e => toast.error(e.message),
    })
  }

  return <Card>
    <CardHeader><CardTitle>운용 원칙</CardTitle>
      <CardDescription>지키고 싶은 원칙을 문장으로 적으면 시스템이 ‘기계가 점검할 규칙’과 ‘대화에서 참고할 원칙’으로 나눠 보여 줍니다. 확인한 그대로 저장되고, 규칙은 장중 30분·장 마감 뒤 점검해 어긴 순간 텔레그램으로 한 번 알립니다. 원문은 이 컴퓨터의 DB에만 저장됩니다.</CardDescription></CardHeader>
    <CardContent className="space-y-4">
      {list.isPending ? <Skeleton className="h-20 w-full" />
        : list.isError ? <ErrorState message="원칙을 불러오지 못했습니다." onRetry={() => void list.refetch()} />
        : list.data.length === 0 ? <p className="text-sm text-muted-foreground">아직 저장한 원칙이 없습니다.</p>
        : <ul className="divide-y" aria-label="저장한 운용 원칙">{list.data.map(p => <SavedPrinciple key={p.id} principle={p}
            deleting={remove.isPending} onDelete={() => remove.mutate(p.id, { onError: e => toast.error(e.message) })} />)}</ul>}

      <div className="space-y-2 border-t pt-4">
        <Label htmlFor="principle-text">새 원칙</Label>
        <Textarea id="principle-text" value={text} maxLength={20000} disabled={busy} className="min-h-20"
          placeholder="예: 처음 들어갈 때는 한 종목에 계좌의 25%까지만. 평단 대비 -20%면 기계적으로 손절. 물타기는 하지 않는다."
          onChange={e => { setText(e.target.value); setPreview(null) }} />
        {!preview && <Button variant="outline" size="sm" disabled={busy || text.trim().length < 3} onClick={run}>
          {parse.isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Wand2 className="size-4" />}{parse.isPending ? '정리하는 중…' : '규칙으로 풀기'}</Button>}
      </div>

      {preview && <Interpretation preview={preview} onChange={setPreview} busy={busy} confirmLabel="이대로 저장" onConfirm={confirm} onCancel={() => setPreview(null)} />}
    </CardContent>
  </Card>
}

/** 해석 확인 — 기계 점검 규칙과 대화 참고 원칙을 하나씩 뺄 수 있다. */
function Interpretation({ preview, onChange, busy, confirmLabel, onConfirm, onCancel }: {
  preview: PrincipleParse; onChange: (next: PrincipleParse) => void; busy: boolean; confirmLabel: string; onConfirm: () => void; onCancel: () => void
}) {
  const empty = !preview.rules.length && !preview.unparsed.length
  return <section aria-label="해석한 원칙 확인" className="space-y-3 rounded-lg bg-muted/40 p-3">
    <p className="text-sm font-medium">시스템이 이렇게 이해했습니다 — 맞지 않는 항목은 빼고 저장하세요</p>
    <Understood rules={preview.rules.map(r => r.summary ?? r.type)} notes={preview.unparsed}
      onRemoveRule={i => onChange({ ...preview, rules: preview.rules.filter((_, j) => j !== i) })}
      onRemoveNote={i => onChange({ ...preview, unparsed: preview.unparsed.filter((_, j) => j !== i) })} />
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={busy || empty} onClick={onConfirm}>{busy && <LoaderCircle className="size-4 animate-spin" />}{confirmLabel}</Button>
      <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>취소</Button>
    </div>
  </section>
}

/** ① 기계 점검 규칙 ② 대화에서 참고하는 원칙 — 저장된 원칙과 확인 화면이 같은 모양을 쓴다. */
function Understood({ rules, notes, onRemoveRule, onRemoveNote }: {
  rules: string[]; notes: string[]; onRemoveRule?: (i: number) => void; onRemoveNote?: (i: number) => void
}) {
  return <div className="space-y-3">
    <div className="space-y-1.5">
      <p className="text-caption font-medium">기계 점검 <span className="font-normal text-muted-foreground">· 어기면 텔레그램 알림</span></p>
      {rules.length ? <ul className="flex flex-wrap gap-1.5">{rules.map((r, i) => <li key={i}><Badge variant="secondary" className="gap-1 font-normal">{r}
        {onRemoveRule && <button type="button" aria-label={`${r} 빼기`} className="rounded-sm opacity-70 hover:opacity-100" onClick={() => onRemoveRule(i)}><X className="size-3" /></button>}</Badge></li>)}</ul>
        : <p className="text-caption text-muted-foreground">수치로 점검할 규칙이 없습니다.</p>}
    </div>
    <div className="space-y-1.5">
      <p className="text-caption font-medium">대화에서 참고하는 원칙 <span className="font-normal text-muted-foreground">· ‘내 원칙대로라면?’ 질문의 판단 기준</span></p>
      {notes.length ? <ul className="space-y-1">{notes.map((n, i) => <li key={i} className="flex items-start gap-2 text-sm">
        <span aria-hidden="true" className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" /><span className="min-w-0 flex-1 break-keep">{n}</span>
        {onRemoveNote && <button type="button" aria-label={`${n} 빼기`} className="mt-0.5 shrink-0 rounded-sm text-muted-foreground hover:text-foreground" onClick={() => onRemoveNote(i)}><X className="size-3.5" /></button>}
      </li>)}</ul>
        : <p className="text-caption text-muted-foreground">정리된 목록이 없습니다. ‘다시 풀기’로 원문에서 정리하세요.</p>}
    </div>
  </div>
}

const CLAMP_LINES = 8

/** 저장한 원칙 한 건 — 이해한 내용이 먼저, 원문은 접어 둔다. 원문 수정·다시 풀기·삭제. */
function SavedPrinciple({ principle, deleting, onDelete }: { principle: PortfolioPrinciple; deleting: boolean; onDelete: () => void }) {
  const update = useUpdatePrincipleText()
  const parse = useParsePrinciple()
  const replace = useReplacePrinciple()
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(principle.text)
  const [preview, setPreview] = useState<{ text: string; parsed: PrincipleParse } | null>(null)
  const busy = update.isPending || parse.isPending || replace.isPending
  const long = principle.text.split('\n').length > CLAMP_LINES || principle.text.length > 600

  function saveText() {
    if (draft.trim().length < 3 || busy) return
    update.mutate({ id: principle.id, text: draft.trim() }, {
      onSuccess: () => { setEditing(false); toast.success('원문을 고쳤습니다. 이해한 내용은 그대로입니다.') },
      onError: e => toast.error(e.message),
    })
  }
  function reparse(text: string) {
    if (busy) return
    parse.mutate(text, { onSuccess: parsed => setPreview({ text, parsed }), onError: e => toast.error(e.message) })
  }
  function confirmReplace() {
    if (!preview) return
    replace.mutate({ id: principle.id, text: preview.text, rules: preview.parsed.rules, notes: preview.parsed.unparsed }, {
      onSuccess: () => { setPreview(null); setEditing(false); toast.success('새로 이해한 내용으로 바꿨습니다.') },
      onError: e => toast.error(e.message),
    })
  }

  return <li className="space-y-3 py-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm font-medium">원칙 {principle.id} <span className="font-normal text-caption text-muted-foreground">· 저장 {principle.created_at.slice(0, 10)}</span></p>
      <div className="flex">
        <Button variant="ghost" size="sm" disabled={busy || editing} onClick={() => reparse(principle.text)}>
          {parse.isPending && !editing ? <LoaderCircle className="size-4 animate-spin" /> : <Wand2 className="size-4" />}다시 풀기</Button>
        <Button variant="ghost" size="icon-sm" className="size-9" aria-label="원문 수정" disabled={busy} onClick={() => { setDraft(principle.text); setEditing(true); setPreview(null) }}><Pencil className="size-4" /></Button>
        <Button variant="ghost" size="icon-sm" className="size-9" aria-label="원칙 삭제" disabled={deleting || busy} onClick={onDelete}><Trash2 className="size-4" /></Button>
      </div>
    </div>

    {preview ? <Interpretation preview={preview.parsed} onChange={parsed => setPreview({ ...preview, parsed })} busy={replace.isPending}
        confirmLabel="이 내용으로 교체" onConfirm={confirmReplace} onCancel={() => setPreview(null)} />
      : <div className="space-y-2 rounded-lg border p-3"><p className="text-caption text-muted-foreground">시스템이 이렇게 이해했습니다</p>
        <Understood rules={principle.rules.map(r => r.summary ?? r.type)} notes={principle.notes} /></div>}

    {editing ? <div className="space-y-2">
        <Textarea aria-label="원칙 원문 수정" value={draft} maxLength={20000} disabled={busy} className="min-h-64 text-sm" onChange={e => setDraft(e.target.value)} />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={busy || draft.trim().length < 3} onClick={() => reparse(draft.trim())}>
            {parse.isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Wand2 className="size-4" />}저장하고 다시 풀기</Button>
          <Button size="sm" variant="outline" disabled={busy || draft.trim().length < 3} onClick={saveText}>원문만 저장</Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setEditing(false); setDraft(principle.text); setPreview(null) }}>취소</Button>
        </div>
      </div>
      : <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="-ml-2 h-8 text-muted-foreground">원문 보기<ChevronDown className="size-3.5" /></Button></CollapsibleTrigger>
        <CollapsibleContent className="pt-1">
          <p className={`whitespace-pre-line break-words text-sm leading-relaxed text-muted-foreground ${long && !expanded ? 'line-clamp-8' : ''}`}>{principle.text}</p>
          {long && <Button variant="ghost" size="sm" className="-ml-2 mt-1 h-8 text-muted-foreground" onClick={() => setExpanded(v => !v)}>{expanded ? '접기' : '전체 보기'}</Button>}
        </CollapsibleContent></Collapsible>}
  </li>
}
