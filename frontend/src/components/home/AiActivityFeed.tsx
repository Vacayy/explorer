import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { FileText, LineChart, Route, Sparkles, SquarePlay, Workflow } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ProposalPanel } from "@/components/shared/ProposalPanel"
import { AI_ACTIVITY, useAiActivity, type AiActivityItem } from "@/hooks/useAiActivity"
import { aiCoverageLabel } from "@/lib/canvas"
import { formatKstDateTime } from "@/utils/format"

/* ---------- AI가 최근 만든 것 — 캔버스 › 피드 최상단, AI 생성물이 모이는 한 곳 (D-209, canvas.md §1) ---------- */

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

export function AiActivityFeed() {
  const q = useAiActivity()
  const items = q.data ?? []
  if (q.isLoading) return <Skeleton className="h-28 w-full rounded-xl" />
  return (
    <ProposalPanel
      icon={Sparkles} title="AI가 최근 만든 것" subtitle={`${aiCoverageLabel(items.map(a => a.created_at), AI_ACTIVITY.limit, AI_ACTIVITY.days, formatKstDateTime)} · 최신순`}
      count={q.isError ? undefined : items.length}
      maxHeight="10.25rem" /* 5행: 32px × 5 + 구분선 4px */ maxWidth="100%" contentClassName="px-0 divide-y">
      {q.isError ? (
        <div className="flex items-center gap-3 px-4 py-3 text-sm text-muted-foreground">
          <span>AI 생성물 목록을 불러오지 못했습니다.</span>
          <Button variant="outline" size="sm" onClick={() => void q.refetch()}>다시 시도</Button>
        </div>
      ) : items.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted-foreground">지난 {AI_ACTIVITY.days}일간 자동생성된 콘텐츠가 없습니다.</p>
      ) : items.map((a, i) => {
        const m = ACT_META[a.type] ?? ACT_META.narrative
        return (
          <Link key={`${a.type}-${a.topic}-${i}`} to={actLink(a)}
            className="flex items-center gap-2 px-4 py-1.5 hover:bg-muted/50">
            <m.Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <Badge variant="outline" className={`text-caption shrink-0 ${m.cls}`}>{m.label}</Badge>
            <span className="text-sm truncate min-w-0 flex-1">{a.title}</span>
            <span className="text-caption text-muted-foreground tabular-nums shrink-0">{formatKstDateTime(a.created_at)}</span>
          </Link>
        )
      })}
    </ProposalPanel>
  )
}
