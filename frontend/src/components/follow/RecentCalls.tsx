import { FileAudio } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ProposalPanel } from "@/components/shared/ProposalPanel"
import { ErrorState } from "@/components/shared/ErrorState"
import { formatRelativeTime } from "@/utils/format"
import { useRecentCalls } from "@/hooks/useTranscripts"
const SOURCE: Record<string, string> = { fool: "Motley Fool", alphavantage: "Alpha Vantage" }

/** 최근 받은 컨콜(D-218) — 'AI가 최근 만든 것'과 같은 목록. 누르면 아래 상세에서 그 녹취록을 연다. */
export function RecentCalls({ onSelect, selectedId }: { onSelect: (id: number) => void; selectedId: string | null }) {
  const q = useRecentCalls(7)
  if (q.isPending) return <Skeleton className="h-32 w-full rounded-xl" />
  if (q.isError) return <ErrorState onRetry={() => void q.refetch()} />
  const items = q.data
  return (
    <ProposalPanel icon={FileAudio} title="최근 받은 컨콜" subtitle="지난 7일 · 받은 순" count={items.length} maxHeight="16rem" maxWidth="100%" contentClassName="px-0 divide-y [contain:inline-size]">
      {items.length === 0
        ? <p className="px-4 py-4 text-sm text-muted-foreground">지난 7일간 새로 받은 컨콜이 없습니다. 매일 07:20에 수집합니다.</p>
        : items.map(c => (
          <Button key={c.transcript_id} variant="ghost" onClick={() => onSelect(c.transcript_id)}
            className={`h-auto w-full justify-start gap-2 rounded-none px-4 py-1.5 font-normal ${selectedId === String(c.transcript_id) ? "bg-muted/60" : ""}`}>
            <Badge variant="outline" className="shrink-0 text-caption tabular-nums">{c.ticker}</Badge>
            <span className="min-w-0 flex-1 truncate text-left text-sm">{c.company_name ?? c.ticker} <span className="text-muted-foreground" title={`회사 회계 FY${c.fiscal_year} ${c.fiscal_period}`}>{c.cy ?? `FY${c.fiscal_year} ${c.fiscal_period}`}{c.call_date ? ` · ${c.call_date.slice(5)} 발표` : ""}</span></span>
            {!c.has_digest && <span className="shrink-0 text-caption text-muted-foreground">요약 대기</span>}
            <span className="hidden shrink-0 text-caption text-muted-foreground sm:inline">{SOURCE[c.provider ?? ""] ?? c.provider}</span>
            <span className="w-16 shrink-0 text-right text-caption tabular-nums text-muted-foreground">{c.fetched_at ? formatRelativeTime(c.fetched_at.replace(" ", "T") + "Z") : ""}</span>
          </Button>
        ))}
    </ProposalPanel>
  )
}
