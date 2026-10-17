import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatLevel, formatPercent, formatRatio } from "@/utils/format"
import type { TwLink } from "@/types"

/** 대만 → 한국 연결 표시 규칙 — 종목 상세 카드와 홈 위젯이 같이 쓴다 (docs/specs/tw-revenue.md §6) */
export const TW_RELATION: Record<TwLink["relation"], string> = { peer: "동종", demand: "고객 수요", capex: "설비 투자" }

const STATE_TONE: Record<string, string> = {
  "가속": "border-up/40 text-up", "전환↑": "border-up/40 text-up",
  "둔화": "border-down/40 text-down", "전환↓": "border-down/40 text-down", "유지": "text-muted-foreground",
}

export function TwStateBadge({ link }: { link: TwLink }) {
  if (!link.state) return null
  return <Badge variant="outline" className={cn("shrink-0 text-[11px]", STATE_TONE[link.state])}
    title={`3개월 YoY ${formatPercent(link.yoy_3m_prev)} → ${formatPercent(link.yoy_3m)} (3개월 전 대비 ±10%p면 가속·둔화)`}>
    {link.state}
  </Badge>
}

/** 숫자 근거 한 줄 — 상관은 분기 YoY, 표본이 작아 '어긋나지 않는지' 확인용 */
export function twEvidenceText(e: TwLink["evidence"]): string {
  if (e.corr == null) return e.n ? `숫자 근거 부족(${e.n}분기)` : "한국 분기 재무 수집 전"
  const lead = e.best_lag ? `대만 ${e.best_lag}분기 선행` : "동행"
  return `${lead} 상관 ${formatLevel(e.corr)} · 같은 방향 ${formatRatio((e.same_dir ?? 0) * 100)} (${e.n}분기)`
}
