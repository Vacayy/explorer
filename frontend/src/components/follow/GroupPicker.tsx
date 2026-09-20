import { useState, type ReactNode } from 'react'
import { FolderPlus, LoaderCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateGroup, useGroups } from '@/hooks/useGroups'
import type { StockGroupKind } from '@/types'

const KIND_LABEL: Record<StockGroupKind, string> = { watch: '관심', portfolio: '포트폴리오' }

/** 묶음 하나를 고르는 메뉴. 발견 후보의 "묶음에 추가", 저장 전략의 "이 조건으로 감시"가 함께 쓴다. */
export function GroupPicker({ label, icon, onPick, busy = false, variant = 'outline', size = 'sm' }: {
  label: string; icon?: ReactNode; onPick: (groupId: number) => Promise<void> | void; busy?: boolean
  variant?: 'outline' | 'ghost' | 'secondary'; size?: 'sm' | 'xs'
}) {
  const groups = useGroups()
  const create = useCreateGroup()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [kind, setKind] = useState<StockGroupKind>('watch')
  async function pick(id: number) {
    try { await onPick(id) } catch (error) { toast.error(error instanceof Error ? error.message : '묶음에 반영하지 못했습니다.') }
  }
  async function submit() {
    if (!name.trim() || create.isPending) return
    try {
      const detail = await create.mutateAsync({ name: name.trim(), kind })
      setCreating(false); setName('')
      await pick(detail.id)
    } catch (error) { toast.error(error instanceof Error ? error.message : '묶음을 만들지 못했습니다.') }
  }
  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button variant={variant} size={size} disabled={busy}>{busy ? <LoaderCircle className="size-3.5 animate-spin" /> : icon}{label}</Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuLabel>{label}</DropdownMenuLabel>
        {groups.isPending && <DropdownMenuItem disabled>묶음을 불러오는 중…</DropdownMenuItem>}
        {groups.isError && <DropdownMenuItem disabled>묶음을 불러오지 못했습니다.</DropdownMenuItem>}
        {groups.data?.items.map(group => <DropdownMenuItem key={group.id} onSelect={() => void pick(group.id)}>
          <span className="min-w-0 flex-1 truncate">{group.name}</span><span className="text-caption text-muted-foreground">{KIND_LABEL[group.kind]} · {group.member_count}종목</span>
        </DropdownMenuItem>)}
        {groups.data && groups.data.items.length === 0 && <DropdownMenuItem disabled>아직 묶음이 없습니다.</DropdownMenuItem>}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setCreating(true)}><FolderPlus className="size-4" />새 묶음 만들기</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <Dialog open={creating} onOpenChange={setCreating}>
      <DialogContent>
        <DialogHeader><DialogTitle>새 묶음</DialogTitle><DialogDescription>관심 종목은 종목만, 포트폴리오는 수량·매수가도 기록합니다.</DialogDescription></DialogHeader>
        <form className="space-y-3" onSubmit={event => { event.preventDefault(); void submit() }}>
          <div className="space-y-2"><Label htmlFor="group-picker-name">이름</Label><Input id="group-picker-name" value={name} onChange={event => setName(event.target.value)} maxLength={80} autoFocus /></div>
          <div className="flex gap-2" role="radiogroup" aria-label="묶음 종류">{(['watch', 'portfolio'] as StockGroupKind[]).map(value => <Button key={value} type="button" role="radio" aria-checked={kind === value} variant={kind === value ? 'secondary' : 'outline'} size="sm" onClick={() => setKind(value)}>{KIND_LABEL[value]}</Button>)}</div>
          <DialogFooter><Button type="button" variant="ghost" onClick={() => setCreating(false)}>취소</Button><Button type="submit" disabled={!name.trim() || create.isPending}>{create.isPending ? '만드는 중…' : '만들고 추가'}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </>
}
