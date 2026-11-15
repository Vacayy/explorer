import { useState } from 'react'
import { toApiError } from '@/api/errors'
import { googleLoginUrl } from '@/api/auth'
import { useMemberAccess } from '@/components/auth/MemberAccess'
import { Button } from '@/components/ui/button'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { useMemberSaved, useSaveMemberDocument, useDeleteMemberSaved } from '@/hooks/useMemberSaved'

export function MemberDocumentSaveButton({ docId }: { docId: number }) {
  const access = useMemberAccess()
  if (access.status === 'loading') return <span role="status" className="text-sm text-ink-3">계정 확인 중…</span>
  if (access.status === 'error') return <Button variant="outline" size="sm" onClick={access.retry}>로그인 확인 재시도</Button>
  if (access.session?.login_available === false) return <span role="status" className="text-sm text-ink-3">로그인 준비 중</span>
  if (access.status !== 'member' && access.status !== 'operator') return <Button asChild variant="outline" size="sm"><a href={googleLoginUrl(`/doc/${docId}`)}>로그인하고 문서 저장</a></Button>
  return <DocumentSave key={`${access.session!.user!.id}:${access.status}:${docId}`} docId={docId} />
}
function DocumentSave({ docId }: { docId: number }) {
  const access = useMemberAccess()
  const [authLost, setAuthLost] = useState(false)
  const query = useMemberSaved(0, docId)
  const save = useSaveMemberDocument()
  const remove = useDeleteMemberSaved()
  const [confirming, setConfirming] = useState(false)
  const item = query.data?.items.find(row => row.doc_id === docId)
  const mutationError = (error: unknown) => { if ([401,403].includes(toApiError(error).status ?? 0)) setAuthLost(true) }
  const busy = save.isPending || remove.isPending || query.isFetching
  if (authLost) return <Button variant="outline" size="sm" onClick={() => { access.retry(); void query.refetch().then(result => { if (!result.error) setAuthLost(false) }) }}>로그인 권한 다시 확인</Button>
  if (query.error) return <div className="flex flex-wrap items-center gap-2"><p role="alert" className="text-sm">저장 상태를 확인하지 못했습니다.</p><Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>저장 상태 다시 확인</Button></div>
  if (!query.data || query.isFetching) return <span role="status" className="text-sm text-ink-3">저장 상태 확인 중…</span>
  return <div className="space-y-2">
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" disabled={busy} aria-pressed={!!item} onClick={() => {
        save.reset(); remove.reset()
        if (item) setConfirming(true)
        else save.mutate({ doc_id: docId }, { onError: mutationError })
      }}>{item ? item.status === 'changed' ? '이전 공개본 저장됨 · 해제' : '저장됨 · 해제' : '내 문서에 저장'}</Button>
    </div>
    {item?.status === 'changed' && <p className="text-sm text-ink-3">저장 이후 내용이 변경되었습니다. 현재 공개본은 저장한 버전과 다릅니다.</p>}
    {(save.error || remove.error) && <p role="alert" className="text-sm">저장 상태를 변경하지 못했습니다. 다시 시도해 주세요.</p>}
    <AlertDialog open={confirming} onOpenChange={setConfirming}><AlertDialogContent><AlertDialogHeader>
      <AlertDialogTitle>이 문서의 저장을 해제할까요?</AlertDialogTitle><AlertDialogDescription>이 항목에 남긴 본인 메모도 삭제됩니다.</AlertDialogDescription>
    </AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>취소</AlertDialogCancel><AlertDialogAction onClick={() => { if (item) remove.mutate(item.id, { onError: mutationError }) }}>저장 해제</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </div>
}
