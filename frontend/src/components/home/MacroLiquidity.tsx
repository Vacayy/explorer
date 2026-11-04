import { AlertTriangle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BlockError, tone } from "@/components/home/blockState"
import { InfoTip } from "@/components/regimes/Section"
import { useMacro } from "@/hooks/useMacro"
import { cn } from "@/lib/utils"
import type { MacroIndicator } from "@/types"

/**
 * 매크로·유동성 신호등 — 홈 › 매크로 (docs/specs/macro.md, ia-redesign §4.16 #8).
 * 매크로(키 없음, yfinance)·유동성(FRED). 순유동성 = Fed BS − TGA − RRP (MacroMicro US Liquidity Index).
 * 시장 국면(포스처)·1번 추세 신호와 규칙이 다르다 — 엇갈려도 둘 다 보인다. 갱신은 아침 브리핑 작업이 맡는다(사용자 화면에 버튼 없음).
 * compact = 모바일 핵심 6지표(Mobile-Macro).
 */
const LIGHT: Record<string, { label: string; cls: string }> = {
  green: { label: "초록 · 확대", cls: "border-chart-profit/40 bg-chart-profit/10 text-chart-profit-dark" },
  yellow: { label: "노랑 · 선별", cls: "border-hypothesis/40 bg-hypothesis/10 text-hypothesis" },
  red: { label: "빨강 · 방어", cls: "border-destructive/40 bg-destructive/10 text-destructive" },
}
const COMPACT_KEYS = ["usdkrw", "us10y", "dxy", "net_liq", "hyg", "oil"]

const GROUP_ORDER: { key: string; label: string }[] = [
  { key: "rates", label: "금리·달러" },
  { key: "liquidity", label: "유동성" },
  { key: "credit", label: "신용·위험선호" },
  { key: "commodity", label: "원자재" },
]

const HINT = "전날 미국장의 배경 조건입니다 — 금리·달러(위험선호 방향), 순유동성(Fed BS−TGA−RRP, 위험자산과 가장 잘 붙는 유동성), 신용·원자재. 위 1번 추세 신호와 규칙이 달라 둘이 엇갈릴 수 있습니다. 변화는 약 20거래일 전 대비입니다."

export function fmtValue(m: MacroIndicator): string {
  const v = m.value
  if (m.key === "usdkrw" || m.key === "jpykrw") return `${v.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}원`
  if (m.fmt === "pct") return `${v.toFixed(2)}%`
  if (m.fmt === "usd") return `$${v.toLocaleString("en-US", { maximumFractionDigits: v >= 100 ? 0 : 2 })}`
  if (m.fmt === "trillion_b") return `$${v.toFixed(2)}T`
  return v.toLocaleString("en-US", { maximumFractionDigits: 2 })
}

function MiniSpark({ data }: { data: number[] }) {
  if (data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data)
  const span = max - min || 1
  const w = 140, h = 22
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * h}`).join(" ")
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-[22px] w-full min-w-0 overflow-visible" aria-hidden>
      <polyline points={pts} fill="none" strokeWidth={1.25} vectorEffect="non-scaling-stroke" className="stroke-foreground/70" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function Row({ m }: { m: MacroIndicator }) {
  const c = m.change_pct
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto_4.5rem] items-center gap-3 border-b py-2 last:border-0">
      <span className="truncate text-sm">{m.label}</span>
      <MiniSpark data={m.series} />
      <span className="text-right font-mono text-sm tabular-nums">{fmtValue(m)}</span>
      <span className={cn("text-right font-mono text-sm tabular-nums", tone(c))}>{c == null ? "-" : `${c > 0 ? "+" : ""}${c.toFixed(2)}%`}</span>
    </div>
  )
}

export function MacroLiquidity({ compact }: { compact?: boolean }) {
  const { data, isLoading, isError, error, refetch } = useMacro()
  const head = <CardHeader className="flex flex-row flex-wrap items-center gap-1.5 space-y-0">
    <CardTitle>매크로·유동성 신호등</CardTitle>
    <InfoTip label="매크로·유동성 설명">{HINT}</InfoTip>
    {data?.as_of && <span className="text-caption tabular-nums text-muted-foreground">{data.as_of}</span>}
  </CardHeader>
  if (isLoading) return <Card id="macro" className="scroll-mt-24">{head}<CardContent><Skeleton className="h-56 w-full" /></CardContent></Card>
  if (isError || !data) return <Card id="macro" className="scroll-mt-24">{head}<CardContent><BlockError message="매크로·유동성을 불러오지 못했습니다" error={error} onRetry={() => void refetch()} /></CardContent></Card>

  const byGroup = (g: string) => data.items.filter((m) => m.group === g)
  const light = data.signal ? LIGHT[data.signal.signal] : null
  return (
    <Card id="macro" className="scroll-mt-24" data-macro-block="macro">
      {head}
      <CardContent className="space-y-3">
        {(light || data.interpretation) && <div className="flex flex-wrap items-center gap-2">
          {light && <Badge variant="outline" className={cn("font-medium", light.cls)}>{light.label}</Badge>}
          {data.interpretation && <Badge variant="outline" className={cn("font-normal", data.interpretation.stance === "우호" ? "border-up/40 text-up" : data.interpretation.stance === "역풍" ? "border-down/40 text-down" : "text-muted-foreground")}>배경 {data.interpretation.stance}</Badge>}
          {data.signal && <span className="text-sm font-semibold">{data.signal.headline}</span>}
        </div>}
        {!compact && (data.signal ? <p className="max-w-4xl text-sm leading-relaxed">{data.signal.comment}</p>
          : data.interpretation && <p className="text-sm text-muted-foreground">{data.interpretation.comment.replace(/ → 위험자산 배경 \S+$/, "")}</p>)}
        {compact ? <div>{COMPACT_KEYS.map(k => data.items.find(m => m.key === k)).filter((m): m is MacroIndicator => !!m).map(m => <Row key={m.key} m={m} />)}</div>
          : <div className="surface-grid grid md:grid-cols-2">
            {GROUP_ORDER.map(({ key, label }) => {
              const items = byGroup(key)
              return (
                <div key={key} className="min-w-0 border px-4 py-3">
                  <div className="mb-1 text-caption font-medium text-muted-foreground">{label}</div>
                  {items.length > 0 ? items.map((m) => <Row key={m.key} m={m} />)
                    : key === "liquidity" && !data.fred_enabled ? <p className="py-1 text-caption text-muted-foreground">FRED 키가 없어 순유동성·M2를 받지 못했습니다.</p>
                    : <p className="py-1 text-caption text-muted-foreground">-</p>}
                </div>
              )
            })}
          </div>}
        {data.degraded.length > 0 && <p className="flex items-center gap-1.5 text-caption text-hypothesis">
          <AlertTriangle className="size-3.5" aria-hidden="true" />{data.degraded.join(" · ")} 원천 지연 · 이 지표 없이 판정했습니다
        </p>}
      </CardContent>
    </Card>
  )
}
