import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { SignalSummaryCard, type SummaryRow } from "@/components/explore/SignalSummaryCard"
import { NODE_LABEL } from "@/components/explore/graph/types"

/**
 * Home 신호 대시보드 섹션 — 탐색 해체(D-057)로 신호 요약이 Home으로 이관됨.
 * 언급 모멘텀 · 주목 주제 · 인과 그래프 활동. 전체/상세는 /explore?list= (pill 없는 도시에).
 */

/* ---------- 언급 모멘텀 랭킹 — 이번 주 부상 종목 ---------- */

interface MomentumRow {
  rank: number
  entity_id: number
  name: string
  stock_code: string | null
  count_7d: number
  prior_7d: number
  score: number
  daily: number[]
}

export function MomentumSection() {
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ["spine", "momentum"],
    queryFn: async () => (await api.get("/api/spine/signals/momentum")).data as { items: MomentumRow[] },
    staleTime: 5 * 60_000,
  })
  const rows: SummaryRow[] = (data?.items ?? []).map((m) => ({
    key: String(m.entity_id),
    rank: m.rank,
    name: m.name,
    link: m.stock_code ? `/analyze/${m.stock_code}/mentions` : undefined,
    spark: m.daily,
    metric: `7일 ${m.count_7d}회`,
    sub: `직전 ${m.prior_7d}`,
    badge: m.score >= 2 ? `×${m.score}` : undefined,
  }))
  return (
    <SignalSummaryCard
      title="언급 모멘텀 — 이번 주 부상 종목"
      rows={rows}
      onOpen={() => navigate("/explore?list=mention_surge")}
    />
  )
}

/* ---------- 주목 주제 (theme_surge) ---------- */

export function ThemeSurgeSummary() {
  const navigate = useNavigate()
  const { data } = useSpineSignals("theme_surge", 14)
  const rows: SummaryRow[] = (data?.items ?? []).map((s, i) => ({
    key: String(s.id),
    rank: i + 1,
    name: s.entity_name,
    link: `/narrative?topic=${encodeURIComponent(s.entity_name)}`,
    metric: `비중 ${s.payload.share_pct ?? "-"}%`,
    sub: `${s.payload.recent ?? 0}건`,
    badge: s.payload.is_new ? "신규" : (s.payload.share_delta_pp ? `+${s.payload.share_delta_pp}%p` : undefined),
  }))
  return (
    <SignalSummaryCard
      title="주목 주제 — 지금 소스들이 몰리는 화두"
      subtitle="전체 문서 중 비중 상승"
      rows={rows}
      onOpen={() => navigate("/explore?list=theme_surge")}
    />
  )
}

/* ---------- 인과 그래프 활동 — 새로 뜬/갱신된 노드 + 수혜 종목 (action_thesis, D-035) ---------- */

interface ActivityBeneficiary { stock_code: string; name: string; rs_short: number | null }
interface GraphActivityNode {
  id: number; name: string; type: string; is_new: boolean; new_edges: number
  beneficiaries: ActivityBeneficiary[]
}

export function GraphActivitySection() {
  const { data } = useQuery(
    apiQuery<GraphActivityNode[]>({
      key: ["spine", "causal", "activity"],
      url: "/api/spine/causal/activity?days=7&limit=10",
      staleTime: STALE.medium,
    }),
  )
  const items = data ?? []
  if (items.length === 0) return null
  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <CardTitle className="text-sm">인과 그래프 — 최근 뜬 고리</CardTitle>
        <span className="text-[11px] text-muted-foreground">새로 추가·갱신된 노드와 수혜 종목</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((n) => (
          <Link key={n.id} to={`/narrative?topic=${encodeURIComponent(n.name)}`} className="block group">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-medium text-sm group-hover:underline">{n.name}</span>
              <Badge variant="outline" className="text-[9px]">{NODE_LABEL[n.type] ?? n.type}</Badge>
              {n.is_new
                ? <span className="text-[10px] text-up">신규</span>
                : <span className="text-[10px] text-muted-foreground tabular-nums">갱신 +{n.new_edges}</span>}
            </div>
            {n.beneficiaries.length > 0 && (
              <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
                수혜 후보: {n.beneficiaries.map((b) => `${b.name}${b.rs_short != null ? ` (RS ${b.rs_short})` : ""}`).join(" · ")}
              </div>
            )}
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}
