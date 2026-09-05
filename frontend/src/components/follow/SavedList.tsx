// 저장됨 목록 — 헤더 Sheet(compact)와 /follow/saved 페이지 공용 (D-078)
import { useState } from "react"
import { Link } from "react-router-dom"
import { Bookmark, Building2, FileBarChart, FileText, Layers, Network, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { formatRelativeTime } from "@/utils/format"
import { useRemoveSaved, useUpdateSavedNote, type SavedItem, type SavedKind } from "@/hooks/useSaved"

const KIND_META: Record<SavedKind, { icon: typeof Bookmark; label: string }> = {
  company: { icon: Building2, label: "기업" },
  doc: { icon: FileText, label: "문서" },
  narrative: { icon: Network, label: "내러티브" },
  report: { icon: FileBarChart, label: "리포트" },
  synthesis: { icon: Layers, label: "종합" },
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
  selectedDocIds,
  onToggleDoc,
}: {
  items: SavedItem[]
  compact?: boolean
  onNavigate?: () => void
  /** 선택 모드(D-104 교차 종합) — 넘기면 문서 행에 체크박스. 문서 kind만 선택 가능 */
  selectedDocIds?: number[]
  onToggleDoc?: (docId: number) => void
}) {
  const remove = useRemoveSaved()
  const selectable = !!onToggleDoc && !!selectedDocIds
  return (
    <ul className="divide-y">
      {items.map((it) => {
        const Meta = KIND_META[it.kind]
        const Icon = Meta?.icon ?? Bookmark
        const docId = it.kind === "doc" ? Number(it.ref) : null
        const checked = docId != null && !!selectedDocIds?.includes(docId)
        return (
          <li key={it.id} className="flex items-start gap-3 py-3">
            {selectable && (
              docId != null && Number.isFinite(docId) ? (
                <Checkbox
                  className="mt-0.5 shrink-0"
                  checked={checked}
                  onCheckedChange={() => onToggleDoc?.(docId)}
                  aria-label={`${it.title || it.url} 종합 대상으로 선택`}
                />
              ) : (
                <span className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              )
            )}
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
                <span className="ml-auto shrink-0">{when(it.created_at)}</span>
              </div>
              {compact
                ? it.note && <p className="mt-1 text-xs text-muted-foreground">{it.note}</p>
                : <NoteEditor item={it} />}
            </div>
            <Button
              variant="ghost"
              size="icon-xs"
              className="shrink-0 text-muted-foreground"
              title="삭제"
              aria-label="저장 해제"
              onClick={() => remove.mutate(it.id, { onSuccess: () => toast("저장 해제됨") })}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </li>
        )
      })}
    </ul>
  )
}

function NoteEditor({ item }: { item: SavedItem }) {
  const [note, setNote] = useState(item.note ?? "")
  const update = useUpdateSavedNote()
  const commit = () => {
    const next = note.trim()
    if (next === (item.note ?? "")) return
    update.mutate({ id: item.id, note: next || null })
  }
  return (
    <Input
      value={note}
      onChange={(e) => setNote(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur() }}
      placeholder="메모 추가…"
      className="mt-1.5 h-7 text-xs"
    />
  )
}
