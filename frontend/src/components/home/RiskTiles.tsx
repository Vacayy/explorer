import { BlockError, tone } from "@/components/home/blockState"
import { InfoTip } from "@/components/regimes/Section"
import { SparkLine } from "@/components/shared/Spark"
import { riskChange, riskValue } from "@/components/widgets/market"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { RISK_TILE_KEYS, useRiskTiles } from "@/hooks/useRisk"
import { fearGreedZone, lastMonths, longRangePosition } from "@/lib/macroPage"
import { cn } from "@/lib/utils"
import type { RiskIndicator } from "@/types"

type TileKey = typeof RISK_TILE_KEYS[number]
const GROUPS: { label: string; keys: TileKey[]; cols: string }[] = [
  { label: "금리", keys: ["us2y", "us10y", "curve"], cols: "lg:grid-cols-3" },
  { label: "신용", keys: ["hy", "bbb", "aaa", "baa10y", "aaa10y"], cols: "lg:grid-cols-5" },
  { label: "심리", keys: ["vix", "fear_greed"], cols: "lg:grid-cols-2" },
]
const POSITION_CLS = { 높음: "border-hypothesis/40 bg-hypothesis/10 text-hypothesis", 보통: "text-muted-foreground", 낮음: "border-down/40 text-down-ink" }

/**
 * 리스크 지표 묶음 — 홈 › 매크로 (ia-redesign 결정: 리스크 지표 묶음을 매크로에 둔다).
 * 타일 = 값 · 20일 변화 · 장기 위치 배지(최근 5년, 관측이 짧으면 있는 만큼) · 6개월 추이선. 갱신은 예약 작업(snapshot_market)이 맡는다.
 * 한 지표가 갱신에 실패하면 그 타일만 마지막 값을 흐리게 두고 기준 날짜를 붙인다(상태 시트 §4.28).
 */
export function RiskTiles({ compact }: { compact?: boolean }) {
  const q = useRiskTiles()
  const items = Object.fromEntries((q.data?.items ?? []).map(i => [i.key, i])) as Record<string, RiskIndicator | undefined>
  const signal = q.data?.signal
  return <Card id="risk" className="scroll-mt-24" data-macro-block="risk">
    <CardHeader className="flex flex-row flex-wrap items-center gap-1.5 space-y-0">
      <CardTitle>리스크 지표</CardTitle>
      <InfoTip label="리스크 지표 설명">미국 금리·신용·변동성·투자심리의 일별 저장 관측입니다. 배지는 최근 5년(관측이 더 짧으면 있는 만큼) 안에서 지금 값의 위치로, 상위 20%면 높음·하위 20%면 낮음입니다. 추이선은 최근 6개월입니다.
        {signal && <> 경계 실험 규칙({signal.rule_version}): 20 공통 관측일 10Y ≤ −30bp · HY OAS ≥ +75bp가 3회 지속되면 경계. 침체 확정 신호가 아닙니다.</>}</InfoTip>
      {signal && signal.status !== "unavailable" && <Badge variant="outline" className={cn("font-normal", ["joint", "watch", "credit"].includes(signal.status) && "border-hypothesis/40 text-hypothesis")} title={signal.reason}>{signal.label}</Badge>}
      {!compact && <a href="#overlay" className="ml-auto text-xs text-muted-foreground hover:text-foreground">겹쳐 보기 ›</a>}
    </CardHeader>
    <CardContent className="space-y-3">
      {q.isPending ? <div className="space-y-3">{GROUPS.map(g => <Skeleton key={g.label} className="h-28 w-full" />)}</div>
        : q.isError ? <BlockError message="리스크 지표를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
        : GROUPS.map(g => <div key={g.label} className="space-y-1.5">
          <p className="text-caption font-medium text-muted-foreground">{g.label}</p>
          <div className={cn("surface-grid grid grid-cols-2", g.cols)}>
            {g.keys.map(k => <Tile key={k} item={items[k]} compact={compact} />)}
          </div>
        </div>)}
      {q.data?.empty && <p className="text-sm text-muted-foreground">아직 리스크 관측이 없습니다. 예약 수집이 돌면 채워집니다.</p>}
    </CardContent>
  </Card>
}

function Tile({ item, compact }: { item?: RiskIndicator; compact?: boolean }) {
  if (!item) return <div className="border px-3 py-2.5 text-sm text-muted-foreground">-</div>
  const fresh = item.quality === "fresh"
  const pos = item.key === "fear_greed" ? null : longRangePosition(item.points, item.value, item.as_of)
  const zone = item.key === "fear_greed" ? fearGreedZone(item.value) : null
  const spark = lastMonths(item.points, item.as_of, 6).map(p => p[1])
  const day = item.as_of ? item.as_of.slice(5, 10).replace("-", "/") : null
  return <div className="min-w-0 border px-3 py-2.5" data-risk-tile={item.key}>
    <div className="flex items-center justify-between gap-2">
      <span className="truncate text-caption text-muted-foreground">{item.label}</span>
      {pos && <Badge variant="outline" className={cn("shrink-0 px-1.5 py-0 text-[11px] font-normal", POSITION_CLS[pos.position])}>{pos.years}년 {pos.position}</Badge>}
      {zone && <Badge variant="outline" className={cn("shrink-0 px-1.5 py-0 text-[11px] font-normal", (item.value ?? 50) < 45 ? POSITION_CLS.높음 : "text-muted-foreground")}>{zone}</Badge>}
    </div>
    <div className={cn("mt-1 flex flex-wrap items-baseline gap-x-2", !fresh && "opacity-60")}>
      <span className={cn("font-mono font-medium tabular-nums", compact ? "text-base" : "text-lg")}>{riskValue(item.unit, item.value)}</span>
      <span className={cn("whitespace-nowrap font-mono text-caption tabular-nums", tone(item.change_20))}>20일 {riskChange(item.unit, item.change_20)}</span>
    </div>
    {!fresh && <p className="text-[11px] text-warn">{item.quality === "stale" ? `${item.lag_days ?? "?"}일 지연` : item.quality === "missing" ? "미수집" : "갱신 실패"}{day ? ` · ${day} 값` : ""}</p>}
    {!compact && spark.length > 1 && <div className={cn("mt-2", !fresh && "opacity-60")}><SparkLine data={spark} height={34} /></div>}
  </div>
}

