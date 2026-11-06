// 저장됨 목록 — 헤더 Sheet(compact)와 피드 › 저장됨(/feed/saved) 공용 (D-078)
import { useState } from "react"
import { Link } from "react-router-dom"
import { Bookmark, Building2, FileBarChart, FileText, MessageSquare, Network, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { InPlaceMore } from "@/components/shared/Bounded"
import { formatRelativeTime } from "@/utils/format"
import { useRemoveSaved, useUpdateSavedNote, type SavedItem, type SavedKind } from "@/hooks/useSaved"

const KIND_META: Record<SavedKind, { icon: typeof Bookmark; label: string }> = {
  company: { icon: Building2, label: "기업" },
  doc: { icon: FileText, label: "문서" },
  narrative: { icon: Network, label: "내러티브" },
  report: { icon: FileBarChart, label: "리포트" },
  chat: { icon: MessageSquare, label: "대화" },
}

/** SQLite datetime('now')는 UTC 공백 포맷 — ISO UTC로 정규화 후 상대시각 */
function when(created_at: string | null): string {
  if (!created_at) return "-"
  return formatRelativeTime(created_at.includes("T") ? created_at : created_at.replace(" ", "T") + "Z")
}

export default function SavedList({
  items,
  compact = false,
  onNavigate,
}: {
  items: SavedItem[]
  compact?: boolean
  onNavigate?: () => void
}) {
  const remove = useRemoveSaved()
  // 페이지에서는 메모가 있는 줄만 메모를 보이고, 메모 쓰기는 누른 줄에만 펼친다(ia-redesign §4.26)
  const [editing, setEditing] = useState<number | null>(null)
  const list = (
    <ul className="divide-y">
      {items.map((it) => {
        const Meta = KIND_META[it.kind]
        const Icon = Meta?.icon ?? Bookmark
        return (
          <li key={it.id} className={compact ? "flex items-start gap-3 py-3" : "group flex items-start gap-3 px-4 py-3 hover:bg-muted/50"} data-saved-row={it.id}>
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <Link
                to={it.url}
                onClick={onNavigate}
                className="block truncate text-sm font-medium hover:underline"
              >
                {it.title || it.url}
              </Link>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                <span>{Meta?.label ?? it.kind}</span>
                {it.subtitle && <span className="truncate">· {it.subtitle}</span>}
                {compact && <span className="ml-auto shrink-0">{when(it.created_at)}</span>}
              </div>
              {compact || editing !== it.id
                ? it.note && <p className="mt-1 text-xs text-muted-foreground">{it.note}</p>
                : <NoteEditor item={it} onDone={() => setEditing(null)} />}
            </div>
            {!compact && <span className="shrink-0 pt-0.5 text-xs tabular-nums text-muted-foreground">{when(it.created_at)}</span>}
            {/* 메모·저장 해제는 줄에 마우스를 올리면 나온다. 터치 기기(pointer-coarse)는 항상 보인다 */}
            <div className={compact ? "contents" : "flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 pointer-coarse:opacity-100"}>
              {!compact && (
                <Button variant="secondary" size="xs" aria-label={`${it.title || "항목"} 메모`} aria-expanded={editing === it.id}
                  onClick={() => setEditing(editing === it.id ? null : it.id)}>
                  메모
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon-xs"
                className="shrink-0 text-muted-foreground"
                title="저장 해제"
                aria-label="저장 해제"
                onClick={() => remove.mutate(it.id, { onSuccess: () => toast("저장 해제됨") })}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          </li>
        )
      })}
    </ul>
  )
  // 페이지 목록은 상한(lg) 안에서 — 메모 쓰기를 펼쳐도 펼치기 직전 높이 그대로 안에서 스크롤(헤더 Sheet는 시트가 스크롤)
  return compact ? list : <InPlaceMore open={editing != null} size="lg">{list}</InPlaceMore>
}

function NoteEditor({ item, onDone }: { item: SavedItem; onDone: () => void }) {
  const [note, setNote] = useState(item.note ?? "")
  const update = useUpdateSavedNote()
  const commit = () => {
    const next = note.trim()
    if (next !== (item.note ?? "")) update.mutate({ id: item.id, note: next || null })
    onDone()
  }
  return (
    <Input
      autoFocus
      aria-label="메모"
      value={note}
      onChange={(e) => setNote(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur()
        if (e.key === "Escape") onDone()
      }}
      placeholder="메모 추가…"
      className="mt-1.5 h-7 text-xs"
    />
  )
}
