import { useState } from "react"
import { LineChart, Line, YAxis, Tooltip, ResponsiveContainer } from "recharts"
import { Gauge, Info } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { MetricHint } from "@/components/shared/MetricHint"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { formatNumber } from "@/utils/format"
import { useMarketRegime } from "@/hooks/useMarketRegime"
import type { MarketPostureKR, MarketPostureUS, MarketSeries, PostureColor } from "@/types"

/**
 * 시장 국면 — 홈 매크로 리스크 포스처 섹션 (D-076, docs/specs/market-regime.md).
 * 지표 = fact (F&G·VIX·RSI·EMA). 결합 포스처·근거 = frame (결정적 규칙, 정답 아님).
 * 미국 = 글로벌 리스크 날씨 · 국장 = 매매 본판. BLUF = 국장 포스처.
 */
/* ── "왜 이 지표를 보는가" 해설 (제품 안 1클릭, 신호는 근거와 함께) ── */
const HINT = {
  section:
    "매일 아침 '오늘 얼마나 실어도 되나'를 판단하는 매크로 리스크 포스처. " +
    "감성 오실레이터(공포·탐욕)로 진입 타이밍을, 그 20일 EMA 기울기로 추세를, 변동성으로 포지션 크기를 읽어 " +
    "하나의 비중 포스처로 결합합니다. 지표는 사실(fact), 포스처 해석은 하나의 관점(frame)일 뿐입니다.",
  fg:
    "Fear & Greed(0=극단 공포 ~ 100=극단 탐욕): 미국 시장 심리의 극단을 재는 오실레이터. " +
    "역발상 — 공포 극단은 매수 기회, 탐욕 극단은 경계. " +
    "실선=F&G, 파선=그 20일 EMA(추세). 오실레이터가 바닥서 반등해도 EMA가 우하향이면 추세 미전환 → 비중 확대 보류(반등 속임수 경계).",
  rsi:
    "RSI14: 국장은 직접 F&G가 없어 모멘텀 오실레이터로 대체. 30 미만 과매도, 70 초과 과열. " +
    "실선=RSI, 파선=그 20일 EMA. F&G와 같은 규율 — 반등해도 EMA가 눕기 전엔 보류.",
  vix:
    "VIX(공포지수): S&P500 옵션 내재변동성. 높을수록 시장 불확실성이 커 포지션은 작게(사이징 축소). " +
    "20 미만 안정 · 20~30 경계 · 30 초과 위험.",
  vol:
    "국장 변동성(VKOSPI 또는 KOSPI 20일 실현변동성 — 미국 VIX의 국장판). 높을수록 리스크가 커 포지션 축소. " +
    "VKOSPI 미수집 시 KOSPI 실현변동성으로 대체.",
} as const

export function MarketRegime() {
  const { data, isLoading, isError, refetch, refresh, refreshing } = useMarketRegime()

  if (isLoading) return <Skeleton className="h-52 w-full rounded-xl" />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />
  if (!data.kr && !data.us) return null   // Empty — 델타 섹션에 자리 양보

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Gauge className="h-4 w-4 text-muted-foreground" /> 시장 국면
          <MetricHint hint={HINT.section}>
            <Info className="h-3.5 w-3.5 text-muted-foreground" />
          </MetricHint>
          {data.degraded.length > 0 && (
            <Badge variant="outline" className="text-[10px] font-normal text-muted-foreground">
              일부 지표 미수집: {data.degraded.join(", ")}
            </Badge>
          )}
          <span className="ml-auto flex items-center gap-1.5">
            {data.as_of && <FreshnessStamp asOf={data.as_of} />}
            <RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트 (시장 지표 재수집)" />
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* BLUF — 국장 포스처 헤드라인 (없으면 미국) */}
        <Bluf color={(data.kr ?? data.us)!.posture_color}
          posture={(data.kr ?? data.us)!.posture} reason={data.headline} />

        <div className="grid grid-cols-1 @[620px]/market:grid-cols-2 gap-4">
          {data.us && <UsColumn us={data.us} />}
          {data.kr && <KrColumn kr={data.kr} />}
        </div>
      </CardContent>
    </Card>
  )
}

/* ── 포스처 시맨틱 (신호등 — 가격 방향과 무관) ── */
const POSTURE_VAR: Record<PostureColor, string> = {
  favorable: "var(--color-chart-green)",
  caution: "var(--color-chart-warning)",
  risk: "var(--color-chart-negative)",
  neutral: "var(--color-muted-foreground)",
}
const DIR_LABEL: Record<string, string> = { up: "↗ 상승", flat: "→ 횡보", down: "↘ 하락", unknown: "—" }
const FG_ZONE: Record<string, string> = {
  extreme_fear: "극단적 공포", fear: "공포", neutral: "중립", greed: "탐욕", extreme_greed: "극단적 탐욕",
}
const BAND_LABEL: Record<string, string> = { calm: "안정", elevated: "경계", stress: "위험" }
const OSC_ZONE: Record<string, string> = { oversold: "과매도", overbought: "과열", neutral: "중립" }

/** "YYYY-MM-DD" → "MM/DD" */
const fmtDate = (d: string) => (d.length >= 10 ? d.slice(5).replace("-", "/") : d)

function Dot({ color }: { color: PostureColor }) {
  return <span className="inline-block h-2.5 w-2.5 rounded-full shrink-0" style={{ background: POSTURE_VAR[color] }} />
}

function Bluf({ color, posture, reason }: { color: PostureColor; posture: string; reason: string }) {
  return (
    <div className="flex items-start gap-2">
      <Dot color={color} />
      <div className="min-w-0">
        <span className="text-sm font-semibold" style={{ color: POSTURE_VAR[color] }}>{posture}</span>
        <span className="text-sm text-foreground"> — {reason}</span>
      </div>
    </div>
  )
}

function PostureTag({ color, posture }: { color: PostureColor; posture: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ color: POSTURE_VAR[color] }}>
      <Dot color={color} />{posture}
    </span>
  )
}

function ColHeader({ flag, color, posture }: { flag: string; color: PostureColor; posture: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs font-semibold text-muted-foreground">{flag}</span>
      <PostureTag color={color} posture={posture} />
    </div>
  )
}

/* ── 미국 (날씨): F&G 오실레이터 + 20 EMA(게이트) × VIX ── */
function UsColumn({ us }: { us: MarketPostureUS }) {
  return (
    <div className="space-y-2.5">
      <ColHeader flag="🌎 미국" color={us.posture_color} posture={us.posture} />
      <OscBlock label="Fear & Greed" hint={HINT.fg} osc={us.series.osc} ema={us.series.osc_ema} dir={us.trend.dir}
        latest={us.fear_greed ? formatNumber(us.fear_greed.score) : "-"}
        zone={us.fear_greed ? (FG_ZONE[us.fear_greed.zone] ?? us.fear_greed.zone) : ""} />
      {us.vix && (
        <MetricRow label="VIX" hint={HINT.vix} value={formatNumber(us.vix.value)}
          sub={BAND_LABEL[us.vix.band] ?? us.vix.band}
          series={us.series.vix} color="var(--color-chart-warning)" />
      )}
    </div>
  )
}

/* ── 국장 (본판): RSI14 오실레이터 + 20 EMA(게이트) × 변동성 ── */
function KrColumn({ kr }: { kr: MarketPostureKR }) {
  return (
    <div className="space-y-2.5">
      <ColHeader flag="🇰🇷 한국" color={kr.posture_color} posture={kr.posture} />
      <OscBlock label="RSI14" hint={HINT.rsi} osc={kr.series.osc} ema={kr.series.osc_ema} dir={kr.trend.dir}
        latest={formatNumber(kr.oscillator.value)}
        zone={OSC_ZONE[kr.oscillator.zone] ?? kr.oscillator.zone} />
      {kr.volatility && (
        <MetricRow label={kr.volatility.metric} hint={HINT.vol} value={formatNumber(kr.volatility.value)}
          sub={BAND_LABEL[kr.volatility.band] ?? kr.volatility.band}
          series={kr.series.vol} color="var(--color-chart-blue)" />
      )}
    </div>
  )
}

/** 오실레이터 + 그 20 EMA 오버레이 — EMA 기울기 = 추세 게이트 (태린이 아빠 규율).
 *  hover 시 그 시점의 오실레이터·EMA 값+날짜로 전환. */
function OscBlock({ label, hint, osc, ema, dir, latest, zone }: {
  label: string; hint: string; osc: MarketSeries; ema: MarketSeries; dir: string; latest: string; zone: string
}) {
  const [hi, setHi] = useState<number | null>(null)
  const ho = hi != null ? osc[hi] : undefined
  const he = hi != null ? ema[hi] : undefined
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-xs gap-2">
        <MetricHint hint={hint}>
          <span className="text-muted-foreground shrink-0 underline decoration-dotted decoration-muted-foreground/40 underline-offset-2">
            {label} <span className="opacity-70">+ 20 EMA</span>
          </span>
        </MetricHint>
        {ho ? (
          <span className="tabular-nums truncate">
            {formatNumber(ho[1])}
            {he && <span className="text-muted-foreground"> · EMA {formatNumber(he[1])}</span>}
            <span className="text-muted-foreground"> · {fmtDate(ho[0])}</span>
          </span>
        ) : (
          <span className="tabular-nums truncate">
            {latest} <span className="text-muted-foreground">{zone} · EMA {DIR_LABEL[dir] ?? dir}</span>
          </span>
        )}
      </div>
      <Overlay osc={osc} ema={ema} onHover={setHi} />
    </div>
  )
}

function MetricRow({ label, hint, value, sub, series, color }: {
  label: string; hint: string; value: string; sub: string; series: MarketSeries; color: string
}) {
  const [hi, setHi] = useState<number | null>(null)
  const hov = hi != null ? series[hi] : undefined   // hover 시 그 시점 값·날짜로 전환
  return (
    <div className="flex items-center gap-2">
      <div className="w-28 shrink-0">
        <MetricHint hint={hint}>
          <div className="text-xs text-muted-foreground w-fit underline decoration-dotted decoration-muted-foreground/40 underline-offset-2">{label}</div>
        </MetricHint>
        <div className="text-sm tabular-nums">
          {hov ? formatNumber(hov[1]) : value}{" "}
          <span className="text-[11px] text-muted-foreground">{hov ? fmtDate(hov[0]) : sub}</span>
        </div>
      </div>
      <div className="flex-1 min-w-0"><Sparkline data={series} color={color} onHover={setHi} /></div>
    </div>
  )
}

/** onMouseMove state → hover 인덱스 (recharts activeTooltipIndex는 number|string) */
const hoverIdx = (s: { activeTooltipIndex?: number | string | null }): number | null => {
  const i = typeof s?.activeTooltipIndex === "string" ? Number(s.activeTooltipIndex) : s?.activeTooltipIndex
  return typeof i === "number" && Number.isFinite(i) ? i : null
}

/* ── 스파크라인 (Recharts, 축·격자 숨김, hover=활성점+외부 라벨) ── */
function Sparkline({ data, color, height = 34, onHover }: {
  data: MarketSeries; color: string; height?: number; onHover?: (i: number | null) => void
}) {
  if (!data?.length) return null
  const d = data.map(([x, y]) => ({ x, y }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={d} margin={{ top: 3, bottom: 3, left: 0, right: 0 }}
        onMouseMove={(s) => onHover?.(hoverIdx(s))} onMouseLeave={() => onHover?.(null)}>
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Tooltip content={() => null} cursor={{ stroke: "var(--border)", strokeWidth: 1 }} />
        <Line type="monotone" dataKey="y" stroke={color} strokeWidth={1.5} dot={false}
          activeDot={{ r: 2.5, fill: color, strokeWidth: 0 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** 오실레이터(실선) vs 그 20 EMA(파선) 오버레이 — 기울기(추세 게이트) 시각화 + hover */
function Overlay({ osc, ema, height = 48, onHover }: {
  osc: MarketSeries; ema: MarketSeries; height?: number; onHover?: (i: number | null) => void
}) {
  if (!osc?.length) return null
  const emaMap = new Map(ema.map(([x, y]) => [x, y]))
  const d = osc.map(([x, y]) => ({ x, o: y, e: emaMap.get(x) ?? null }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={d} margin={{ top: 3, bottom: 3, left: 0, right: 0 }}
        onMouseMove={(s) => onHover?.(hoverIdx(s))} onMouseLeave={() => onHover?.(null)}>
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Tooltip content={() => null} cursor={{ stroke: "var(--border)", strokeWidth: 1 }} />
        <Line type="monotone" dataKey="o" stroke="var(--color-chart-orange)" strokeWidth={1.5} dot={false}
          activeDot={{ r: 2.5, fill: "var(--color-chart-orange)", strokeWidth: 0 }} isAnimationActive={false} connectNulls />
        <Line type="monotone" dataKey="e" stroke="var(--color-chart-blue)" strokeWidth={1.5} strokeDasharray="3 2"
          dot={false} activeDot={{ r: 2.5, fill: "var(--color-chart-blue)", strokeWidth: 0 }} isAnimationActive={false} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  )
}
