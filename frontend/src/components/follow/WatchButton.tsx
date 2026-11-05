import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useDefaultWatchGroup, useToggleWatch } from '@/hooks/useGroups'

/** ★ — 기본 관심 묶음('관심 종목')에 넣고 뺀다. 관심 종목의 진실원천은 stock_groups 하나(국내 종목코드·미국 티커 모두). */
export function WatchButton({ stockCode }: { stockCode: string }) {
  const group = useDefaultWatchGroup()
  const toggle = useToggleWatch()
  if (!group.data) return null
  const watched = group.data.members.some((m) => m.stock_code === stockCode)
  return (
    <Button
      variant="outline"
      size="xs"
      aria-pressed={watched}
      disabled={toggle.isPending}
      onClick={() =>
        toggle.mutate(
          { stockCode, watched: !watched },
          {
            onSuccess: (detail) => toast.success(watched ? `‘${detail.name}’에서 뺐습니다` : `‘${detail.name}’에 추가했습니다`),
            onError: (e) => toast.error(e instanceof Error && e.message ? e.message : '관심 종목을 바꾸지 못했습니다'),
          },
        )
      }
    >
      <span className={watched ? 'text-warn' : undefined}>{watched ? '★' : '☆'}</span> 관심 종목
    </Button>
  )
}
