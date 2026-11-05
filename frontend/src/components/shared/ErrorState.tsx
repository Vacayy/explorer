import { toApiError } from "@/api/errors"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { RotateCw, TriangleAlert } from "lucide-react"

interface Props {
  error?: unknown
  retrying?: boolean
  message?: string
  onRetry?: () => void
}

/** 오류 — 평평한 면 + 경고 아이콘·문구 + '다시 시도'(DS-Components 5-state) */
export function ErrorState({ message, error, onRetry, retrying = false }: Props) {
  return (
    <Card role="alert">
      <CardContent className="flex flex-col items-start gap-2.5 p-4">
        <p className="flex items-center gap-1.5 text-[13px] text-ink-2"><TriangleAlert className="size-3.5 shrink-0" aria-hidden />{message ?? (error ? toApiError(error).message : "데이터를 불러올 수 없습니다.")}</p>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}><RotateCw className="size-3.5" aria-hidden />{retrying ? "다시 시도 중…" : "다시 시도"}</Button>
        )}
      </CardContent>
    </Card>
  )
}

export function EmptyState({ message = "데이터가 없습니다." }: { message?: string }) {
  return (
    <div role="status" className="py-16 text-center text-[13px] text-ink-2">{message}</div>
  )
}
