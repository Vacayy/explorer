import { toApiError } from "@/api/errors"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

interface Props {
  error?: unknown
  retrying?: boolean
  message?: string
  onRetry?: () => void
}

export function ErrorState({ message, error, onRetry, retrying = false }: Props) {
  return (
    <Card role="alert" className="border-destructive/20">
      <CardContent className="py-10 text-center space-y-3">
        <p className="text-muted-foreground text-sm">{message ?? (error ? toApiError(error).message : "데이터를 불러올 수 없습니다.")}</p>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>{retrying ? "다시 시도 중…" : "다시 시도"}</Button>
        )}
      </CardContent>
    </Card>
  )
}

export function EmptyState({ message = "데이터가 없습니다." }: { message?: string }) {
  return (
    <div role="status" className="py-16 text-center text-muted-foreground text-sm">{message}</div>
  )
}
