import { RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"

/** '지금 업데이트' — 하루 1회 갱신되는 카드의 수동 새로고침 버튼. pending 시 스핀·비활성. */
export function RefreshButton({ onClick, pending, title = "지금 업데이트", label }: {
  onClick: () => void
  pending: boolean
  title?: string
  /** 글자 붙은 알약(시안 Home-KR '↻ 갱신') */
  label?: string
}) {
  if (label) return (
    <Button variant="ghost" size="sm" onClick={onClick} disabled={pending} title={title}
      className="h-8 gap-1.5 rounded-full px-3 text-[13px] font-medium text-ink-2 hover:text-ink">
      <RefreshCw className={pending ? "animate-spin" : ""} aria-hidden />{label}
    </Button>
  )
  return (
    <Button
      variant="ghost" size="icon-xs" onClick={onClick} disabled={pending}
      title={title} aria-label={title} className="text-muted-foreground hover:text-foreground"
    >
      <RefreshCw className={pending ? "animate-spin" : ""} />
    </Button>
  )
}
