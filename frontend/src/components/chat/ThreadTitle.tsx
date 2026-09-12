import { useEffect, useRef, useState } from "react"
import { Check, Pencil, X } from "lucide-react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { renameConversation, spineKeys } from "@/api/spine"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

/**
 * 스레드 제목 — 클릭하면 그 자리에서 편집 (D-145).
 * 자동 제목은 첫 질문 60자라 스레드가 자라면 내용과 어긋난다. Enter 저장 · Esc 취소.
 */
export function ThreadTitle({ id, title }: { id: number; title: string | null }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title ?? "")
  const inputRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()

  useEffect(() => { setDraft(title ?? "") }, [title, id])
  useEffect(() => { if (editing) inputRef.current?.select() }, [editing])

  const save = useMutation({
    mutationFn: renameConversation,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: spineKeys.conversations() })
      qc.invalidateQueries({ queryKey: spineKeys.conversation(id) })
      setEditing(false)
    },
  })

  const commit = () => {
    const t = draft.trim()
    if (!t || t === (title ?? "")) { setEditing(false); setDraft(title ?? ""); return }
    save.mutate({ id, title: t })
  }

  if (editing) {
    return (
      <span className="flex min-w-0 flex-1 items-center gap-1">
        <Input
          ref={inputRef}
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); commit() }
            if (e.key === "Escape") { setEditing(false); setDraft(title ?? "") }
          }}
          onBlur={commit}
          aria-label="대화 제목"
          className="h-7 min-w-0 flex-1 rounded-lg text-sm"
        />
        <Button variant="ghost" size="icon-xs" aria-label="저장" onMouseDown={(e) => e.preventDefault()} onClick={commit}>
          <Check className="size-3" />
        </Button>
        <Button variant="ghost" size="icon-xs" aria-label="취소"
          onMouseDown={(e) => { e.preventDefault(); setEditing(false); setDraft(title ?? "") }}>
          <X className="size-3" />
        </Button>
      </span>
    )
  }

  return (
    <span className="group/title flex min-w-0 items-center gap-1">
      <button type="button" onClick={() => setEditing(true)} title="제목 편집"
        className="min-w-0 truncate rounded px-1 text-sm font-medium hover:bg-muted">
        {title || "(제목 없음)"}
      </button>
      <Pencil className="size-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/title:opacity-100" aria-hidden />
    </span>
  )
}
