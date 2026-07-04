import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

interface Props {
  message?: string
  onRetry?: () => void
}

export function ErrorState({ message = "데이터를 불러올 수 없습니다.", onRetry }: Props) {
  return (
    <Card className="border-destructive/20">
      <CardContent className="py-10 text-center space-y-3">
        <p className="text-muted-foreground text-sm">{message}</p>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>다시 시도</Button>
        )}
      </CardContent>
    </Card>
  )
}

export function EmptyState({ message = "데이터가 없습니다." }: { message?: string }) {
  return (
    <div className="py-16 text-center text-muted-foreground text-sm">{message}</div>
  )
}
