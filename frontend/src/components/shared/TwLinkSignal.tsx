import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatLevel, formatPercent, formatRatio } from "@/utils/format"
import type { KrConfirm, KrDirection, TwLink } from "@/types"

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

const DIR_LABEL: Record<string, string> = { up: "↑", down: "↓", flat: "→" }
const DIR_TONE: Record<string, string> = { up: "text-up", down: "text-down", flat: "text-muted-foreground" }

/** 세 원천 방향 한 줄 — 대만 · 수출 · 공시. 관측 못 한 원천은 '-' */
export function KrConfirmStrip({ c }: { c: KrConfirm }) {
  const trade = c.trade.find(t => t.hs === c.trade_counted)
  const d = c.disclosure
  const cells: { label: string; dir: KrDirection; detail: string }[] = [
    { label: "대만", dir: c.directions.taiwan, detail: c.taiwan ? `3M YoY ${formatPercent(c.taiwan.yoy_3m)}` : "연결 없음" },
    { label: "수출", dir: c.directions.trade,
      detail: trade ? `${trade.note.split(" — ")[0].split("(")[0]} 3M YoY ${formatPercent(trade.yoy_3m)}` : c.trade.length ? "맞는 품목 확신도 낮음(집계 제외)" : "맞는 품목 없음" },
    { label: "공시", dir: c.directions.disclosure,
      detail: `공급계약 90일 ${d.contracts_90d}건(직전 ${d.contracts_prev_90d})${d.capex_180d ? ` · 시설투자 ${d.capex_180d}` : ""}` },
  ]
  return <div className="space-y-1">
    <div className="grid gap-1.5 sm:grid-cols-3">
      {cells.map(x => <div key={x.label} className="rounded-md border px-2 py-1.5 text-caption">
        <span className="font-medium">{x.label}</span>{" "}
        <span className={cn("font-semibold", x.dir ? DIR_TONE[x.dir] : "text-muted-foreground")}>{x.dir ? DIR_LABEL[x.dir] : "-"}</span>
        <span className="block truncate text-muted-foreground" title={x.detail}>{x.detail}</span>
      </div>)}
    </div>
    <p className="text-caption text-muted-foreground">
      관측한 {c.observed}개 원천 중 {c.agree_up}개 상승
      {d.last_prelim && <> · 마지막 잠정실적 공시 {d.last_prelim.date.slice(4, 6)}/{d.last_prelim.date.slice(6)}</>}
    </p>
  </div>
}
