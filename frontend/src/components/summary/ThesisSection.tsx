import { useState } from "react"
import { X } from "lucide-react"
import { useIRNotes, useCreateIRNote, useDeleteIRNote } from "@/hooks/useIRNotes"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/**
 * 내 논지 — Bull/Bear/Catalyst/Risk 4분면 (P2-1: 보관함 투자메모에서 도시에로 이관).
 * 기계의 브리프 옆에 사람의 판단을 나란히 — AI 브리프의 thesis_check가 이걸 근거로
 * 새 증거와의 충돌을 짚는다. 항목 변경 = 브리프 inputs_hash 변경 → 다음 열람 시 재생성.
 */

const QUADRANTS = [
  { key: "bull", label: "Bull — 상승 논거", color: "text-red-600" },
  { key: "bear", label: "Bear — 하락 논거", color: "text-blue-600" },
  { key: "catalyst", label: "Catalyst — 촉매", color: "text-amber-600" },
  { key: "risk", label: "Risk — 위험", color: "text-muted-foreground" },
] as const

export default function ThesisSection({ stockCode }: { stockCode: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">내 논지</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
        {QUADRANTS.map((qd) => (
          <Quadrant key={qd.key} stockCode={stockCode} memoType={qd.key} label={qd.label} color={qd.color} />
        ))}
      </CardContent>
    </Card>
  )
}

function Quadrant({ stockCode, memoType, label, color }: {
  stockCode: string
  memoType: string
  label: string
  color: string
}) {
  const { data: notes = [], isLoading } = useIRNotes(stockCode, memoType)
  const create = useCreateIRNote(stockCode)
  const del = useDeleteIRNote(stockCode)
  const [adding, setAdding] = useState(false)

  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-1 mb-1">
        <span className={cn("text-[11px] font-semibold", color)}>{label}</span>
        <button
          onClick={() => setAdding(!adding)}
          className="ml-auto text-[11px] text-muted-foreground hover:text-foreground"
        >
          +
        </button>
      </div>
      {isLoading ? (
        <Skeleton className="h-4 w-full" />
      ) : (
        <ul className="space-y-1">
          {notes.length === 0 && !adding && (
            <li className="text-[11px] text-muted-foreground">아직 없음</li>
          )}
          {notes.map((n) => (
            <li key={n.id} className="group flex items-start gap-1 text-xs">
              <span className="min-w-0">
                <span className="font-medium">{n.title}</span>
                {n.content && <span className="text-muted-foreground"> — {n.content}</span>}
              </span>
              <button
                onClick={() => del.mutate(n.id)}
                className="shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
                aria-label="삭제"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
          {adding && (
            <li>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  const v = new FormData(e.currentTarget).get("v")?.toString().trim()
                  if (v) {
                    create.mutate(
                      { title: v, memo_type: memoType, note_date: new Date().toISOString().slice(0, 10) },
                      { onSuccess: () => setAdding(false) },
                    )
                  }
                }}
              >
                <input
                  name="v" autoFocus disabled={create.isPending}
                  placeholder="논거 한 줄…"
                  className="w-full h-6 rounded border bg-background px-1.5 text-[11px] outline-none focus:ring-1 focus:ring-ring"
                  onKeyDown={(e) => e.key === "Escape" && setAdding(false)}
                />
              </form>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
