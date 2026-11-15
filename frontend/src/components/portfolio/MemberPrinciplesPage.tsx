import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMemberAccess } from '@/components/auth/MemberAccess'
import { googleLoginUrl } from '@/api/auth'
import { toApiError } from '@/api/errors'
import { useMemberPrinciples, useMemberPrincipleState, useMemberPrincipleOptions, useSaveMemberPrinciple, useDeleteMemberPrinciple } from '@/hooks/useMemberPrinciples'
import { PageContainer } from '@/components/shared/PageContainer'
import { QueryState } from '@/components/shared/QueryState'
import { ErrorState } from '@/components/shared/ErrorState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import type { PortfolioPrinciple, MemberPrincipleInput, MemberPrincipleRuleOption, MemberRuleCoverage } from '@/types'

export function MemberPrinciplesPage() {
  const access = useMemberAccess()
  if (access.status === 'loading') return <PageContainer><Skeleton className="h-40" /><span role="status">계정 확인 중…</span></PageContainer>
  if (access.status === 'error') return <PageContainer><ErrorState message="로그인 상태를 확인할 수 없습니다." onRetry={access.retry} /></PageContainer>
  if (access.status !== 'member' && access.status !== 'operator') return <PageContainer>
    <h1 className="text-xl font-medium">내 운용 원칙</h1><p>로그인하면 본인의 운용 원칙을 저장하고 점검할 수 있습니다.</p>
    <Button asChild><a href={googleLoginUrl('/portfolio/principles')}>Google 로그인</a></Button>
  </PageContainer>
  return <Principles key={`${access.session!.user!.id}:${access.status}`} />
}

const STATUS: Record<MemberRuleCoverage['status'], string> = { evaluated: '평가함', partial: '일부만 평가', unavailable: '평가할 자료 부족', not_applicable: '현재 보유 대상 없음' }
const REASONS: Record<string, string> = {
  'Peak-exit requires market and at least 252 stored prices before entry': '시장 구분과 편입 전 시세 252개 이상이 필요합니다. 부족한 종목은 고점 규칙을 평가하지 않았습니다.',
  'Only holdings with verified peak-exit inputs were evaluated': '시장 구분과 시세 이력이 충분한 종목만 고점 규칙을 평가했습니다.',
  'Shared exposure evidence is not connected': '공통 변수의 근거 자료 연결을 준비 중입니다.',
  'Complete peak-exit price history is not verified': '고점·이동평균 판단에 필요한 시세 이력 검증이 남아 있습니다.',
  'Historical entry valuation is not verified': '매수 당시 계좌 평가 자료 검증이 남아 있습니다.',
  'Complete historical account valuation is not verified': '계좌 전체 기간의 평가 자료 검증이 남아 있습니다.',
  'Some holdings have no stored price': '시세가 없는 보유 종목이 있어 비중을 판단하지 않았습니다.',
  'Account valuation is unavailable': '계좌 평가에 필요한 거래·시세 자료가 없습니다.',
  'Required holding inputs are unavailable': '보유 종목의 평가에 필요한 자료가 없습니다.',
  'Only holdings with complete inputs were evaluated': '자료가 있는 보유 종목만 평가했습니다.',
  'No current holdings': '현재 보유 종목이 없습니다.',
}
function Principles() {
  const access = useMemberAccess(); const list = useMemberPrinciples(); const state = useMemberPrincipleState()
  const options = useMemberPrincipleOptions(); const save = useSaveMemberPrinciple(); const remove = useDeleteMemberPrinciple()
  const [editing, setEditing] = useState<PortfolioPrinciple | 'new' | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const denied = [list.error, state.error, options.error, save.error, remove.error].some(e => e && [401, 403].includes(toApiError(e).status ?? 0))
  if (denied) return <PageContainer><ErrorState message="계정 접근 권한을 다시 확인해 주세요." onRetry={() => { access.retry(); save.reset(); remove.reset(); void list.refetch(); void state.refetch(); void options.refetch() }} /></PageContainer>
  return <PageContainer>
    <header className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-xl font-medium">내 운용 원칙</h1>
      <Button variant="outline" asChild><Link to="/portfolio">내 포트폴리오</Link></Button></header>
    <p className="text-sm text-muted-foreground">저장한 원칙은 본인 계정에서만 조회합니다. 현재는 이 화면에서 점검하며 알림은 발송하지 않습니다.</p>
    <QueryState query={list} emptyMessage="아직 저장한 운용 원칙이 없습니다.">{items => <ul className="divide-y" aria-label="내 운용 원칙 목록">{items.map(item => <li key={item.id} className="space-y-2 py-4">
      <p className="whitespace-pre-wrap break-words">{item.text}</p>
      {item.rules.length > 0 && <ul className="text-sm">{item.rules.map((rule, i) => <li key={i}>{rule.summary ?? rule.type}</li>)}</ul>}
      {item.notes.length > 0 && <div><p className="text-sm font-medium">참고할 원칙</p><ul className="list-inside list-disc text-sm">{item.notes.map((note, i) => <li className="break-words" key={i}>{note}</li>)}</ul></div>}
      <div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => { save.reset(); setEditing(item) }}>수정</Button>
        <Button variant="outline" size="sm" disabled={remove.isPending} onClick={() => { remove.reset(); setDeleting(item.id) }}>삭제</Button></div>
    </li>)}</ul>}</QueryState>
    {remove.error && <p role="alert">삭제하지 못했습니다. 다시 시도해 주세요.</p>}
    {!editing && <Button className="self-start" onClick={() => { save.reset(); setEditing('new') }}>원칙 추가</Button>}
    {editing && <QueryState query={options} emptyMessage="사용할 규칙 정보를 불러오지 못했습니다.">{definitions =>
      <PrincipleEditor key={editing === 'new' ? 'new' : editing.id} initial={editing === 'new' ? undefined : editing} options={definitions}
        busy={save.isPending} failed={save.isError} onCancel={() => setEditing(null)} onSave={body => save.mutate({ id: editing === 'new' ? undefined : editing.id, body }, { onSuccess: () => setEditing(null) })} />}</QueryState>}
    <section className="space-y-3 border-t pt-4"><h2 className="text-lg font-medium">현재 원칙 점검</h2>
      <QueryState query={state} isEmpty={value => value.rules === 0} emptyMessage="수치로 점검할 규칙이 아직 없습니다.">{value => <>
        {value.as_of && <p className="text-sm text-muted-foreground">시세 시점 참고: {value.as_of}</p>}
        <p className="text-sm text-muted-foreground">종목마다 시세 갱신 시점이 다를 수 있으며 실시간 평가가 아닙니다. 고점 규칙은 저장된 시세 관측값을 사용하며 거래일 이력의 완전성을 보장하지 않습니다.{value.price_dates.length > 1 && ` 보유 종목 시세 날짜: ${value.price_dates.join(', ')}`}</p>
        <ul className="space-y-2">{value.coverage.map(item => <li key={`${item.principle_id}:${item.rule_index}`}>
          <p className="text-sm">{item.rule} · {STATUS[item.status]}</p>
          {item.reason && <p className="text-sm text-muted-foreground">{REASONS[item.reason] ?? '필요한 자료를 확인하고 있습니다.'}</p>}
        </li>)}</ul>
        {value.items.length > 0 ? <ul className="space-y-2" aria-label="확인할 원칙 위반">{value.items.map(item => <li key={item.key} className="text-sm">{item.message}</li>)}</ul>
          : <p className="text-sm">{value.coverage.every(item => item.status === 'evaluated') ? '평가한 규칙에서 위반이 발견되지 않았습니다.' : '확인된 위반은 없습니다. 평가하지 못한 항목은 준수 여부를 판단할 수 없습니다.'}</p>}
      </>}</QueryState>
    </section>
    <AlertDialog open={deleting !== null} onOpenChange={open => { if (!open) setDeleting(null) }}><AlertDialogContent><AlertDialogHeader>
      <AlertDialogTitle>이 운용 원칙을 삭제할까요?</AlertDialogTitle><AlertDialogDescription>저장한 원문과 확인된 규칙, 참고 목록이 삭제됩니다.</AlertDialogDescription>
    </AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>취소</AlertDialogCancel><AlertDialogAction onClick={() => { if (deleting !== null) remove.mutate(deleting); setDeleting(null) }}>삭제</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </PageContainer>
}

function PrincipleEditor({ initial, options, busy, failed, onSave, onCancel }: { initial?: PortfolioPrinciple; options: MemberPrincipleRuleOption[]; busy: boolean; failed: boolean; onSave: (body: MemberPrincipleInput) => void; onCancel: () => void }) {
  const [text, setText] = useState(initial?.text ?? '')
  const [notes, setNotes] = useState(initial?.notes.join('\n') ?? '')
  const [rules, setRules] = useState(initial?.rules ?? [])
  const cleanedNotes = notes.split('\n').map(note => note.trim()).filter(Boolean)
  const valid = text.trim().length >= 3 && cleanedNotes.length <= 60 && cleanedNotes.every(note => note.length <= 500) && (rules.length > 0 || cleanedNotes.length > 0)
    && rules.every(rule => { const option = options.find(o => o.type === rule.type); const v = option && rule.params[option.parameter]; return option && v != null && Number.isFinite(v) && v >= option.minimum && v <= option.maximum && (option.parameter === 'pct' || Number.isInteger(v)) })
  return <section className="space-y-3 border-t py-4" aria-label="운용 원칙 편집">
    {initial && <p className="text-sm">저장하면 원문과 아래 확인된 규칙·참고 목록을 함께 교체합니다.</p>}
    <p className="text-sm text-muted-foreground">문장 자동 해석은 준비 중입니다. 점검할 수치 규칙이나 참고할 원칙을 직접 확인해서 저장해 주세요.</p>
    <Label htmlFor="member-principle-text">원칙 원문</Label><Textarea id="member-principle-text" value={text} maxLength={20000} disabled={busy} onChange={e => setText(e.target.value)} />
    {rules.map((rule, index) => { const option = options.find(o => o.type === rule.type); return <div key={index} className="flex flex-wrap items-center gap-2">
      <Select value={rule.type} disabled={busy} onValueChange={kind => { const def = options.find(o => o.type === kind)!; setRules(rules.map((r, i) => i === index ? { type: kind, params: { [def.parameter]: def.minimum } } : r)) }}>
        <SelectTrigger className="w-full sm:w-64" aria-label={`규칙 ${index + 1} 유형`}><SelectValue /></SelectTrigger><SelectContent>{options.map(o => <SelectItem value={o.type} key={o.type}>{o.label}</SelectItem>)}</SelectContent>
      </Select>
      {option && <><Input type="number" className="w-28" aria-label={`규칙 ${index + 1} 기준값`} min={option.minimum} max={option.maximum} step={option.parameter === 'pct' ? 'any' : 1} value={Number.isFinite(rule.params[option.parameter]) ? rule.params[option.parameter] : ''} disabled={busy}
        onChange={e => setRules(rules.map((r, i) => i === index ? { ...r, params: { [option.parameter]: e.target.value === '' ? NaN : Number(e.target.value) } } : r))} />
        <span className="text-sm">{option.parameter === 'pct' ? '%' : option.parameter === 'days' ? '일' : '개'} ({option.minimum}–{option.maximum})</span></>}
      <Button variant="ghost" disabled={busy} onClick={() => setRules(rules.filter((_, i) => i !== index))}>규칙 제거</Button>
    </div> })}
    <Button variant="outline" disabled={busy || rules.length >= 20 || !options.length} onClick={() => { const first = options[0]; setRules([...rules, { type: first.type, params: { [first.parameter]: first.minimum } }]) }}>수치 규칙 추가</Button>
    <Label htmlFor="member-principle-notes">참고할 원칙 · 한 줄에 하나, 각 500자 이내</Label><Textarea id="member-principle-notes" value={notes} maxLength={30060} disabled={busy} onChange={e => setNotes(e.target.value)} />
    {failed && <p role="alert">저장하지 못했습니다. 입력 내용은 유지됩니다. 입력값과 연결 상태를 확인해 주세요.</p>}
    <div className="flex gap-2"><Button disabled={busy || !valid} onClick={() => onSave({ text: text.trim(), notes: cleanedNotes, rules })}>{busy ? '저장 중…' : '확인한 원칙 저장'}</Button><Button variant="ghost" disabled={busy} onClick={onCancel}>취소</Button></div>
  </section>
}
