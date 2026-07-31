import { RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"

/** '지금 업데이트' — 하루 1회 갱신되는 카드의 수동 새로고침 버튼. pending 시 스핀·비활성. */
export function RefreshButton({ onClick, pending, title = "지금 업데이트" }: {
  onClick: () => void
  pending: boolean
  title?: string
}) {
  return (
    <Button
      variant="ghost" size="icon-xs" onClick={onClick} disabled={pending}
      title={title} aria-label={title} className="text-muted-foreground hover:text-foreground"
    >
      <RefreshCw className={pending ? "animate-spin" : ""} />
    </Button>
  )
}
