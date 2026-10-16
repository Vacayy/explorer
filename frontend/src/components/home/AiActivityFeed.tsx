import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { FileText, LineChart, Route, Sparkles, SquarePlay, Workflow } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ProposalPanel } from "@/components/shared/ProposalPanel"

/* ---------- AI 자동생성 피드 (지난 7일 · 최신순) — Home 피드 탭 최상단 (D-209) ---------- */

interface AiActivityItem {
  type: string; title: string; topic: string; code: string | null; question_id?: number | null; doc_id?: number | null; created_at: string
}
const ACT_META: Record<string, { label: string; Icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  narrative: { label: "내러티브", Icon: Sparkles, cls: "text-hypothesis border-hypothesis/40" },
  mega: { label: "메가", Icon: Workflow, cls: "text-hypothesis border-hypothesis/40" },
  report: { label: "리포트", Icon: FileText, cls: "text-primary border-primary/40" },
  scenario: { label: "파급", Icon: Route, cls: "text-muted-foreground" },
  digest: { label: "요약", Icon: LineChart, cls: "text-muted-foreground" },
  youtube_digest: { label: "유튜브 요약", Icon: SquarePlay, cls: "text-muted-foreground" },
}
function actLink(a: AiActivityItem): string {
  if (a.type === "youtube_digest" && a.doc_id) return `/doc/${a.doc_id}?reading=digest`
  if (a.type === "report") return `/report?topic=${encodeURIComponent(a.topic)}`
  if (a.type === "digest" && a.code) return `/analyze/${a.code}/summary`
  if (a.type === "mega") return "/narrative"
  if (a.type === "scenario") return a.question_id ? `/question/${a.question_id}` : `/narrative?topic=${encodeURIComponent(a.topic)}`
  return `/narrative?topic=${encodeURIComponent(a.topic)}`
}

export function AiActivityFeed() {
  const { data: items = [], isLoading } = useQuery(
    apiQuery<AiActivityItem[]>({ key: ["spine", "home", "ai-activity"], url: "/api/spine/home/ai-activity?days=7", staleTime: STALE.short }),
  )
  if (isLoading) return <Skeleton className="h-28 w-full rounded-xl" />
  return (
    <ProposalPanel
      icon={Sparkles} title="AI가 최근 만든 것" subtitle="지난 7일 · 최신순" count={items.length}
      maxHeight="10.25rem" /* 5행: 32px × 5 + 구분선 4px */ maxWidth="100%" contentClassName="px-0 divide-y">
      {items.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted-foreground">지난 7일간 자동생성된 콘텐츠가 없습니다.</p>
      ) : items.map((a, i) => {
        const m = ACT_META[a.type] ?? ACT_META.narrative
        return (
          <Link key={`${a.type}-${a.topic}-${i}`} to={actLink(a)}
            className="flex items-center gap-2 px-4 py-1.5 hover:bg-muted/50">
            <m.Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <Badge variant="outline" className={`text-caption shrink-0 ${m.cls}`}>{m.label}</Badge>
            <span className="text-sm truncate min-w-0 flex-1">{a.title}</span>
            <span className="text-caption text-muted-foreground tabular-nums shrink-0">{a.created_at.slice(5, 16)}</span>
          </Link>
        )
      })}
    </ProposalPanel>
  )
}
