// 저장 토글 — 4개 페이지(기업·문서·내러티브·리포트) 헤더에 붙는 북마크 버튼 (D-078)
import { Bookmark, BookmarkCheck } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { useSaved, useAddSaved, useRemoveSaved, type SavedKind } from "@/hooks/useSaved"

interface SaveButtonProps {
  kind: SavedKind
  /** 안정 식별자 — company=stockCode · doc=docId · narrative/report=버전 id */
  refId: string
  url: string
  title?: string | null
  subtitle?: string | null
  /** 아이콘 옆 라벨 노출 (기본 아이콘만) */
  showLabel?: boolean
}

export default function SaveButton({ kind, refId, url, title, subtitle, showLabel }: SaveButtonProps) {
  const { data: items = [] } = useSaved()
  const add = useAddSaved()
  const remove = useRemoveSaved()
  const existing = items.find((it) => it.kind === kind && it.ref === refId)
  const saved = !!existing
  const busy = add.isPending || remove.isPending

  const toggle = () => {
    if (busy) return
    if (existing) {
      remove.mutate(existing.id, { onSuccess: () => toast("저장 해제됨") })
    } else {
      add.mutate({ kind, ref: refId, url, title, subtitle }, { onSuccess: () => toast("저장됨") })
    }
  }

  return (
    <Button
      variant={saved ? "secondary" : "ghost"}
      size={showLabel ? "sm" : "icon-sm"}
      onClick={toggle}
      disabled={busy || !refId}
      title={saved ? "저장 해제" : "저장 — 나중에 다시 보기"}
      aria-label={saved ? "저장 해제" : "저장"}
      aria-pressed={saved}
    >
      {saved ? <BookmarkCheck className="h-4 w-4" /> : <Bookmark className="h-4 w-4" />}
      {showLabel && <span className="ml-1.5">{saved ? "저장됨" : "저장"}</span>}
    </Button>
  )
}
