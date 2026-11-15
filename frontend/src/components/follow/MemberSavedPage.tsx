import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { toApiError } from '@/api/errors'
import type { MemberSavedDocument } from '@/types'
import { googleLoginUrl } from '@/api/auth'
import { useMemberAccess } from '@/components/auth/MemberAccess'
import { PageContainer } from '@/components/shared/PageContainer'
import { QueryState } from '@/components/shared/QueryState'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { useMemberSaved, useUpdateMemberSavedNote, useDeleteMemberSaved } from '@/hooks/useMemberSaved'

export function MemberSavedPage() {
  const access = useMemberAccess()
  if (access.status === 'loading') return <PageContainer><Skeleton className="h-40" /><span role="status">계정 확인 중…</span></PageContainer>
  if (access.status === 'error') return <PageContainer><ErrorState message="로그인 상태를 확인할 수 없습니다." onRetry={access.retry} /></PageContainer>
  if (access.status !== 'member' && access.status !== 'operator') return <PageContainer>
    <h1 className="text-xl font-medium">내 저장 문서</h1><p>로그인하면 문서를 저장하고 본인만 볼 수 있는 메모를 남길 수 있습니다.</p>
    <Button asChild><a href={googleLoginUrl('/feed/saved')}>Google 로그인</a></Button>
  </PageContainer>
  return <SavedDocuments key={`${access.session!.user!.id}:${access.status}`} />
}

function SavedDocuments() {
  const access = useMemberAccess()
  const [authLost, setAuthLost] = useState(false)
  const [params, setParams] = useSearchParams()
  const rawOffset = Number(params.get('offset') ?? '0')
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0
  const query = useMemberSaved(offset)
  const go = (value: number) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set('offset', String(value)); else next.delete('offset'); return next })
  return <PageContainer>
    <div className="flex flex-wrap items-center justify-between gap-2"><h1 className="text-xl font-medium">내 저장 문서</h1><Button asChild variant="outline"><Link to="/feed">공개 문서 둘러보기</Link></Button></div>
    <p className="text-sm text-ink-3">문서가 공개되지 않는 상태가 되어도 내 메모를 편집하거나 저장을 해제할 수 있습니다.</p>
    {authLost ? <ErrorState message="로그인 권한을 다시 확인해 주세요. 이전 저장 목록은 숨겼습니다." onRetry={() => { access.retry(); void query.refetch().then(result => { if (!result.error) setAuthLost(false) }) }} retrying={query.isFetching} /> : query.error ? <ErrorState message="저장 목록과 문서 공개 상태를 확인하지 못했습니다. 다시 확인할 때까지 이전 목록을 숨깁니다." onRetry={() => void query.refetch()} retrying={query.isFetching} /> :
      <QueryState query={{ ...query, data: query.isFetching ? undefined : query.data }} isEmpty={value => value.items.length === 0} emptyMessage={offset ? '이 페이지에 저장 문서가 없습니다.' : '아직 저장한 문서가 없습니다. 공개 문서에서 저장을 눌러 주세요.'}>
        {value => <>
          {value.items.some(item => !item.available) && <p role="status" className="mb-3 text-sm text-ink-3">저장 당시와 같은 공개본을 확인할 수 없는 문서가 포함되어 있습니다. 이전 제목은 표시하지 않습니다.</p>}
          <ul className="divide-y">{value.items.map(item => <SavedRow key={item.id} item={item} onAuthError={() => setAuthLost(true)} />)}</ul>
        </>}
      </QueryState>}
    <nav aria-label="저장 문서 페이지" className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={offset === 0 || query.isFetching} onClick={() => go(Math.max(0, offset - 20))}>이전 페이지</Button>
      <Button variant="outline" disabled={authLost || !!query.error || query.isFetching || query.data?.next_offset == null} onClick={() => { if (query.data?.next_offset != null) go(query.data.next_offset) }}>다음 페이지</Button>
    </nav>
    <p className="text-sm text-ink-3">기업·내러티브·리포트·대화 저장의 회원 연결은 준비 중입니다.</p>
  </PageContainer>
}

function SavedRow({ item, onAuthError }: { item: MemberSavedDocument; onAuthError: () => void }) {
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState(item.note ?? '')
  const [confirming, setConfirming] = useState(false)
  const update = useUpdateMemberSavedNote()
  const remove = useDeleteMemberSaved()
  const mutationError = (error: unknown) => { if ([401,403].includes(toApiError(error).status ?? 0)) onAuthError() }
  const busy = update.isPending || remove.isPending
  return <li className="min-w-0 space-y-3 py-4">
    {item.status === 'available' && item.available && item.url === `/doc/${item.doc_id}` ? <Link to={item.url} className="break-words font-medium underline">{item.title || '제목 없는 문서'}</Link>
      : <p className="font-medium">{item.status === 'changed' ? '저장 이후 내용이 변경된 문서' : '현재 공개되지 않은 문서'}</p>}
    {item.status === 'changed' && item.current_url === `/doc/${item.doc_id}` && <Link to={item.current_url} className="inline-block text-sm underline">현재 공개본 보기</Link>}
    <p className="text-caption text-ink-3">저장 시각 {item.created_at}</p>
    {editing ? <div className="space-y-2">
      <Textarea aria-label="내 문서 메모" value={note} maxLength={2000} disabled={busy} onChange={event => setNote(event.target.value)} />
      {update.error && <p role="alert" className="text-sm">메모를 저장하지 못했습니다. 입력 내용은 유지됩니다.</p>}
      <div className="flex flex-wrap gap-2"><Button disabled={busy || note.length > 2000} onClick={() => update.mutate({ id: item.id, note: note || null }, { onSuccess: () => setEditing(false), onError: mutationError })}>메모 저장</Button>
        <Button variant="ghost" disabled={busy} onClick={() => setEditing(false)}>취소</Button></div>
    </div> : <>{item.note && <p className="whitespace-pre-wrap break-words text-sm">{item.note}</p>}
      <Button variant="outline" size="sm" disabled={busy} onClick={() => { setNote(item.note ?? ''); update.reset(); setEditing(true) }}>메모 편집</Button></>}
    <Button variant="outline" size="sm" disabled={busy} onClick={() => { remove.reset(); setConfirming(true) }}>저장 해제</Button>
    {remove.error && <p role="alert" className="text-sm">저장을 해제하지 못했습니다. 다시 시도해 주세요.</p>}
    <AlertDialog open={confirming} onOpenChange={setConfirming}><AlertDialogContent><AlertDialogHeader>
      <AlertDialogTitle>이 문서의 저장을 해제할까요?</AlertDialogTitle><AlertDialogDescription>저장 목록에서 제거되고 이 항목에 남긴 본인 메모도 삭제됩니다.</AlertDialogDescription>
    </AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>취소</AlertDialogCancel><AlertDialogAction onClick={() => remove.mutate(item.id, { onError: mutationError })}>저장 해제</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </li>
}
