import { Activity, Info } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { MetricHint } from "@/components/shared/MetricHint"
import { useMacro } from "@/hooks/useMacro"
import type { MacroIndicator } from "@/types"

/**
 * 매크로·유동성 — 홈 배경 조건 트래킹 (docs/specs/macro.md).
 * 매크로(키 없음, yfinance)·유동성(FRED). 순유동성 = Fed BS − TGA − RRP (MacroMicro US Liquidity Index).
 * 시장 국면(포스처)과 역할 분리 — 이건 '배경 조건'. 버튼 주도 갱신(D-100).
 */
const LIGHT: Record<string, { dot: string; text: string }> = {
  green: { dot: "bg-chart-profit", text: "text-chart-profit" },
  yellow: { dot: "bg-chart-warning", text: "text-chart-warning" },
  red: { dot: "bg-destructive", text: "text-destructive" },
}

const GROUP_ORDER: { key: string; label: string }[] = [
  { key: "rates", label: "금리·달러" },
  { key: "liquidity", label: "유동성" },
  { key: "credit", label: "신용·위험선호" },
  { key: "commodity", label: "원자재" },
]

const HINT = "전날 미국장의 배경 조건 — 금리·달러(위험선호 방향), 순유동성(Fed BS−TGA−RRP, 위험자산과 가장 잘 붙는 유동성), 신용스프레드·원자재. 시장 국면(오늘 얼마나 실을까)과 달리 '판이 어떻게 깔렸나'를 본다."

function fmtValue(m: MacroIndicator): string {
  const v = m.value
  if (m.fmt === "pct") return `${v.toFixed(2)}%`
  if (m.fmt === "usd") return `$${v.toLocaleString("en-US", { maximumFractionDigits: v >= 100 ? 0 : 2 })}`
  if (m.fmt === "trillion_b") return `$${v.toFixed(2)}T`
  return v.toLocaleString("en-US", { maximumFractionDigits: 2 })
}

function MiniSpark({ data }: { data: number[] }) {
  if (data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data)
  const span = max - min || 1
  const w = 64, h = 18
  const pts = data.map((v, i) =>
    `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * h}`).join(" ")
  const up = data[data.length - 1] >= data[0]
  return (
    <svg width={w} height={h} className="shrink-0 overflow-visible">
      <polyline points={pts} fill="none" strokeWidth={1.25}
        className={up ? "stroke-up" : "stroke-down"} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function Tile({ m }: { m: MacroIndicator }) {
  const c = m.change_pct
  return (
    <div className="flex items-center gap-2 py-1 min-w-0">
      <span className="text-xs text-muted-foreground truncate w-24 shrink-0">{m.label}</span>
      <MiniSpark data={m.series} />
      <div className="ml-auto text-right shrink-0">
        <div className="text-sm font-medium tabular-nums leading-tight">{fmtValue(m)}</div>
        {c != null && (
          <div className={`text-[10px] tabular-nums leading-tight ${c > 0 ? "text-up" : c < 0 ? "text-down" : "text-muted-foreground"}`}>
            {c > 0 ? "+" : ""}{c}%
          </div>
        )}
      </div>
    </div>
  )
}

export function MacroLiquidity() {
  const { data, isLoading, isError, refetch, refresh, refreshing } = useMacro()

  if (isLoading) return <Skeleton className="h-44 w-full rounded-xl" />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const byGroup = (g: string) => data.items.filter((m) => m.group === g)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Activity className="h-4 w-4 text-muted-foreground" /> 매크로·유동성
          <MetricHint hint={HINT}><Info className="h-3.5 w-3.5 text-muted-foreground" /></MetricHint>
          <span className="ml-auto flex items-center gap-1.5">
            {data.as_of && <FreshnessStamp asOf={data.as_of} />}
            <RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트 (지표 재수집)" />
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {/* 신호등 해설 — sonnet 산문(우선), LLM 미가용이면 결정적 프레임 폴백 */}
        {data.signal ? (
          <div className="rounded-md bg-muted/40 px-2.5 py-2">
            <div className="flex items-center gap-2">
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${LIGHT[data.signal.signal]?.dot ?? "bg-muted-foreground"}`} />
              <span className={`text-xs font-semibold ${LIGHT[data.signal.signal]?.text ?? "text-foreground"}`}>{data.signal.headline}</span>
              <span className="ml-auto text-[9px] uppercase tracking-wide text-muted-foreground">해석</span>
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{data.signal.comment}</p>
          </div>
        ) : data.interpretation ? (
          <div className="flex items-start gap-1.5 rounded-md bg-muted/40 px-2 py-1.5 text-[11px]">
            <span className={`shrink-0 font-medium ${
              data.interpretation.stance === "우호" ? "text-up"
              : data.interpretation.stance === "역풍" ? "text-down" : "text-muted-foreground"}`}>
              배경 {data.interpretation.stance}
            </span>
            <span className="text-muted-foreground">· {data.interpretation.comment.replace(/ → 위험자산 배경 \S+$/, "")}</span>
          </div>
        ) : null}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
        {GROUP_ORDER.map(({ key, label }) => {
          const items = byGroup(key)
          return (
            <div key={key} className="min-w-0">
              <div className="text-[11px] font-medium text-muted-foreground mb-0.5">{label}</div>
              {items.length > 0 ? (
                items.map((m) => <Tile key={m.key} m={m} />)
              ) : key === "liquidity" && !data.fred_enabled ? (
                <p className="text-[11px] text-muted-foreground py-1">FRED 무료 키(FRED_API_KEY) 설정 시 순유동성·M2 표시</p>
              ) : (
                <p className="text-[11px] text-muted-foreground py-1">데이터 없음</p>
              )}
            </div>
          )
        })}
        </div>
      </CardContent>
    </Card>
  )
}
