import { FileText, LineChart, Route, Sparkles, SquarePlay, Workflow } from "lucide-react"
import type { AiActivityItem } from "@/hooks/useAiActivity"

/* ---------- AI 생성물 표시 규칙 — 캔버스 위젯(widgets/canvas)이 쓴다 (D-209). 피드에는 두지 않는다(ia-redesign §4.5) ---------- */

export const ACT_META: Record<string, { label: string; Icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  narrative: { label: "내러티브", Icon: Sparkles, cls: "text-hypothesis border-hypothesis/40" },
  mega: { label: "메가", Icon: Workflow, cls: "text-hypothesis border-hypothesis/40" },
  report: { label: "리포트", Icon: FileText, cls: "text-primary border-primary/40" },
  scenario: { label: "파급", Icon: Route, cls: "text-muted-foreground" },
  digest: { label: "요약", Icon: LineChart, cls: "text-muted-foreground" },
  youtube_digest: { label: "유튜브 요약", Icon: SquarePlay, cls: "text-muted-foreground" },
}
export function actLink(a: AiActivityItem): string {
  if (a.type === "youtube_digest" && a.doc_id) return `/doc/${a.doc_id}?reading=digest`
  if (a.type === "report") return `/report?topic=${encodeURIComponent(a.topic)}`
  if (a.type === "digest" && a.code) return `/analyze/${a.code}/summary`
  if (a.type === "mega") return "/narrative"
  if (a.type === "scenario") return a.question_id ? `/question/${a.question_id}` : `/narrative?topic=${encodeURIComponent(a.topic)}`
  return `/narrative?topic=${encodeURIComponent(a.topic)}`
}
