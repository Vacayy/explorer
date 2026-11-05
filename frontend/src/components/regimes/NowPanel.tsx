import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { AlertTriangle, ExternalLink } from "lucide-react"
import { toast } from "sonner"
import RegimeChart from "@/components/charts/RegimeChart"
import type { RegimeBandSpec, RegimeSeries } from "@/components/charts/RegimeChart"
import { BlockError } from "@/components/home/blockState"
import { Markdown } from "@/components/shared/Markdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useEraCommentary, useEraState, useGenerateCommentary, usePricing, useSetEraCheck } from "@/hooks/useRegimes"
import { splitCommentary } from "@/lib/macroPage"
import { PREMISE_STATUS, personPath } from "@/lib/person"
import { cn } from "@/lib/utils"
import { formatKstDateTime, formatPercent, formatPp } from "@/utils/format"
import type { EraHeat, EraLayerState, EraPremise, EraStateResponse, RegimesResponse } from "@/types"
import { EpisodePaths } from "./EpisodePaths"
import { PricingCompact, PricingSection } from "./PricingSection"
import { InfoTip, Section } from "./Section"

const HEAT: Record<EraHeat, { label: string; cls: string }> = {
  hot: { label: "뜨거움", cls: "border-up/40 text-up-ink" },
  normal: { label: "보통", cls: "text-muted-foreground" },
  cold: { label: "차가움", cls: "border-down/40 text-down-ink" },
}
const PREMISE = PREMISE_STATUS   // 인물 기록 원장과 같은 배지(lib/person)
const VERDICT = { hot: "뜨거움 우세", cold: "차가움 우세", balanced: "균형" } as const

const Light = ({ on }: { on: boolean }) => <span className={cn("inline-block size-2.5 shrink-0 rounded-full", on ? "bg-up" : "bg-muted-foreground/30")} aria-hidden="true" />

/**
 * 지금 시장 읽기(docs/specs/market-regimes.md §8) — 요약 5칸 · AI 해설 · 1 추세 · 2 금리 · 3 온도 · 5 프라이싱 · 4 구루 전제.
 * 판정은 서버 규칙(pipeline/era.py), AI 해설은 그 결과를 문장으로 옮길 뿐이다.
 * 판정 API가 실패해도 요약 줄의 5번(프라이싱)과 프라이싱 섹션은 그대로 보인다(상태 시트 §4.28).
 * compact = 모바일 요약 화면(Mobile-Macro) — 무거운 표·차트를 덜어 낸다.
 */
export function NowPanel({ regimes, compact }: { regimes?: RegimesResponse; compact?: boolean }) {
  const q = useEraState()
  const d = q.data
  return <div className="surface-stack" data-macro-block="now">
    <Summary data={d} pending={q.isPending} failed={q.isError} onRetry={() => void q.refetch()} />
    <Commentary />
    {q.isPending ? <Skeleton className="h-72 w-full rounded-card" /> : d && <>
      {d.state.available && <StateSection data={d} compact={compact} />}
      {d.meaning.available && <MeaningSection data={d} regimes={regimes} compact={compact} />}
      <TemperatureSection data={d} compact={compact} />
    </>}
    {compact ? <PremisePricingCompact data={d} /> : <>
      <PricingSection />
      {d && <PremiseSection data={d} />}
    </>}
  </div>
}

const STAGE = { none: "신호 없음", warn: "경계", confirm: "확정" } as const

function Summary({ data, pending, failed, onRetry }: { data?: EraStateResponse; pending: boolean; failed: boolean; onRetry: () => void }) {
  const pricing = usePricing(8)
  const count = (s: string) => data?.premises.filter(p => p.status === s).length ?? 0
  const state = data?.state, meaning = data?.meaning, t = data?.temperature
  const tiles = [
    { href: "#now-state", label: "1 추세가 꺾였나", value: state?.available ? STAGE[state.stage] : "-",
      sub: state?.available ? `경계 ${state.warn.on ? "켜짐" : "꺼짐"} · 확정 ${state.confirm.on ? "켜짐" : "꺼짐"}` : failed ? "판정 불러오기 실패" : "", warn: !!state?.available && state.stage !== "none" },
    { href: "#now-meaning", label: "2 금리는 무슨 뜻인가", value: meaning?.regime === "inflation" ? "인플레이션형" : meaning?.regime === "disinflation" ? "디스인플레이션형" : "-",
      sub: meaning?.regime === "inflation" ? "금리 급등이 위험 신호" : meaning?.regime === "disinflation" ? "금리 급락이 위험 신호" : "", warn: !!meaning?.conditional_flag },
    { href: "#now-temp", label: "3 막스식 온도", value: t ? VERDICT[t.verdict] : "-",
      sub: t ? `뜨거움 ${t.hot} · 차가움 ${t.cold} · 보통 ${t.normal}` : "", warn: t?.verdict === "hot" },
    { href: "#now-premises", label: "4 구루 전제", value: data ? `지지 ${count("supports")}` : "-",
      sub: data ? `엇갈림 ${count("mixed")} · 반증 쪽 ${count("challenges")} · 판정 밖 ${count("untestable") + count("nodata")}` : "", warn: false },
    { href: "#now-pricing", label: "5 시장이 반영하는 것", value: pricing.data ? `새로 ${pricing.data.summary.new.length}` : "-",
      sub: pricing.data ? `강해짐 ${pricing.data.summary.stronger.length} · 약해짐 ${pricing.data.summary.weaker.length} · 사라짐 ${pricing.data.summary.faded.length}` : pricing.isError ? "불러오기 실패" : "", warn: false },
  ]
  return <section aria-labelledby="now-summary" className="space-y-2">
    <div className="flex items-center gap-1">
      <h2 id="now-summary" className="text-base font-semibold">지금 시장은</h2>
      <InfoTip label="지금 시장은 설명">판정은 모두 정해진 규칙으로 계산합니다. AI 해설은 이 판정을 문장으로 풀어 줄 뿐, 판정을 바꾸지 않습니다. 칸을 누르면 해당 섹션으로 이동합니다.</InfoTip>
    </div>
    <div className="surface-grid grid grid-cols-2 lg:grid-cols-5">
      {tiles.map((x, i) => <a key={x.href} href={x.href} className={cn("rounded-card border bg-card px-4 py-3 transition-colors hover:bg-muted/50", i === 4 && "max-lg:col-span-2")}>
        <div className="text-caption text-muted-foreground">{x.label}</div>
        {pending && i < 4 ? <Skeleton className="mt-1.5 h-5 w-20" /> : <div className={cn("mt-0.5 text-lg font-semibold", x.warn && "text-up-ink")}>{x.value}</div>}
        <div className="text-caption text-muted-foreground">{x.sub}</div>
      </a>)}
    </div>
    {failed && <p role="alert" className="flex flex-wrap items-center gap-1.5 text-caption text-hypothesis">
      <AlertTriangle className="size-3.5" aria-hidden="true" />지금 판정(1~4)을 불러오지 못했습니다 · 국면 이력과 프라이싱은 정상
      <Button variant="ghost" size="sm" className="h-6 px-1.5 text-caption" onClick={onRetry}>다시 시도</Button>
    </p>}
  </section>
}

function Commentary() {
  const q = useEraCommentary()
  const gen = useGenerateCommentary()
  const [open, setOpen] = useState(false)
  const c = q.data
  const parts = useMemo(() => c?.body ? splitCommentary(c.body.replace(/~/g, "\\~")) : null, [c?.body])
  const run = () => gen.mutate(undefined, { onError: () => toast.error("해설을 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.") })
  const prose = "text-[14px] leading-7 [&_h2]:mt-5 [&_h2]:text-[15px] [&_h2]:font-semibold [&_li]:my-1 [&_p]:my-2"
  return <Card id="now-ai" className="scroll-mt-24">
    <CardHeader className="flex flex-row flex-wrap items-center gap-1.5 space-y-0">
      <CardTitle>AI 해설</CardTitle>
      <InfoTip label="AI 해설 설명">AI가 위 규칙 판정과 최신 하워드 막스 메모를 읽고 옮긴 글입니다. 예측이나 매매 권유가 아닙니다. 숫자가 바뀌어도 자동으로 다시 쓰지 않습니다.</InfoTip>
      {c?.created_at && <span className="text-caption text-muted-foreground">{formatKstDateTime(c.created_at)} 작성</span>}
      <Button size="sm" variant="outline" className="ml-auto" onClick={run} disabled={gen.isPending}>
        {gen.isPending ? <><Spinner className="size-3.5" />쓰는 중…</> : c?.body ? "다시 쓰기" : "해설 쓰기"}
      </Button>
    </CardHeader>
    <CardContent className="space-y-2">
      {q.isPending ? <Skeleton className="h-16 w-full" />
        : q.isError ? <BlockError message="해설을 불러오지 못했습니다." error={q.error} onRetry={() => void q.refetch()} />
        : gen.isPending && !c?.body ? <p className="py-4 text-sm text-muted-foreground">판정 결과와 최신 메모를 읽고 해설을 쓰는 중입니다(30초~1분).</p>
        : !parts ? <p className="py-4 text-sm text-muted-foreground">아직 해설이 없습니다.</p>
        : <>
          {c?.stale && <div className="flex items-center gap-1">
            <Badge variant="outline" className="border-hypothesis/40 bg-hypothesis/10 font-normal text-hypothesis">새 데이터 있음 · 다시 쓰기 권장</Badge>
            <InfoTip label="새 데이터 설명">해설을 쓴 뒤 판정 숫자가 바뀌었습니다. 자동으로 다시 쓰지 않으니 필요하면 '다시 쓰기'를 눌러 주세요.</InfoTip>
          </div>}
          <Collapsible open={open} onOpenChange={setOpen}>
            {!open && <Markdown className={prose}>{parts.lead}</Markdown>}
            <CollapsibleContent><Markdown className={prose}>{c!.body!.replace(/~/g, "\\~")}</Markdown></CollapsibleContent>
            {parts.rest && <CollapsibleTrigger asChild>
              <Button variant="link" size="sm" className="h-auto px-0 text-caption">{open ? "접기" : "전체 보기 ›"}</Button>
            </CollapsibleTrigger>}
          </Collapsible>
        </>}
    </CardContent>
  </Card>
}

type Sig = EraLayerState["warn"] | EraLayerState["confirm"]

function SignalCard({ name, sig, active, detail, compact }: { name: string; sig: Sig; active: boolean; detail: ReactNode; compact?: boolean }) {
  const st = sig.stats
  const stats: [string, string][] = [
    ["과거 켜짐", `${sig.episodes.length}번`],
    ["약세장 포착", `${st.bears_caught}/${st.bears_total}`],
    ["헛경보", `10년에 ${st.false_per_decade}번`],
    ["켜질 때 고점 대비", formatPercent(st.drawdown_at_median)],
    ["이후 추가 하락(중앙)", formatPercent(st.remaining_median)],
  ]
  return <div className={cn("min-w-0 space-y-2 rounded-card border px-4 py-3", active && "border-up/40 bg-up/5")}>
    <div className="flex flex-wrap items-center gap-2">
      <Light on={sig.on} /><span className="text-sm font-semibold">{name}</span>
      <Badge variant="outline" className={cn("font-normal", sig.on ? "border-up/40 text-up-ink" : "text-muted-foreground")}>{sig.on ? "켜짐" : "꺼짐"}</Badge>
      <InfoTip label={`${name} 규칙`}>{sig.label}</InfoTip>
      <span className="ml-auto text-caption text-muted-foreground">
        {compact ? `약세장 ${st.bears_caught}/${st.bears_total} · 헛경보 10년에 ${st.false_per_decade}` : sig.since ? `${sig.since}부터 이 상태` : ""}
      </span>
    </div>
    <p className="text-sm">{detail}</p>
    {!compact && <dl className="grid grid-cols-3 gap-x-3 gap-y-2 sm:grid-cols-5">
      {stats.map(([k, v]) => <div key={k} className="min-w-0"><dt className="truncate text-caption text-muted-foreground">{k}</dt><dd className="tabular-nums">{v}</dd></div>)}
    </dl>}
  </div>
}

function StateSection({ data, compact }: { data: EraStateResponse; compact?: boolean }) {
  const s = data.state
  const [params, setParams] = useSearchParams()
  const which = params.get("era_signal") === "confirm" ? "confirm" : "warn"
  return <Section id="now-state" step={1} title={compact ? "추세가 꺾였나" : "추세가 꺾였나 — 경계와 확정"}
    how={<>하락 추세 이탈을 두 단계로 봅니다. <b>경계</b>는 월말 종가가 12개월 이동평균 아래로 내려간 것 — 빠르지만 10년에 두 번쯤 헛경보가 납니다. <b>확정</b>은 1년 신저가를 깨거나 200일선이 꺾여 내려가는 것 — 늦지만 헛경보가 드뭅니다. 이 판정은 '바닥'이 아니라 '지금 어디쯤인가'를 말합니다.</>}>
    <div className={cn("surface-grid grid", !compact && "md:grid-cols-2")}>
      <SignalCard name="경계" sig={s.warn} active={s.stage === "warn"} compact={compact} detail={<>
        {s.warn.month_end} 월말 종가가 12개월선보다 <span className="tabular-nums">{formatPercent(s.warn.vs_sma_pct)}</span> · 이번 달 잠정 <span className="tabular-nums">{formatPercent(s.warn.provisional_vs_sma_pct)}</span>
        {s.warn.provisional_on !== s.warn.on && <Badge variant="outline" className="ml-1.5 border-warn/40 font-normal text-warn">월말에 바뀔 수 있음</Badge>}
      </>} />
      <SignalCard name="확정" sig={s.confirm} active={s.stage === "confirm"} compact={compact} detail={<>
        1년 신저가 이탈 {s.confirm.new_low ? "있음" : "없음"}{s.confirm.last_new_low && ` (마지막 ${s.confirm.last_new_low})`}
        {" "}· 200일선 기울기 <span className="tabular-nums">{formatPercent(s.confirm.ma200_slope_pct)}</span>{s.confirm.slope_down ? " (하락)" : ""}
      </>} />
    </div>
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">{which === "warn" ? "경계" : "확정"}가 켜진 뒤 1년{compact && ` · 과거 ${s[which].episodes.length}번`}</p>
        <ToggleGroup type="single" size="sm" variant="outline" value={which} aria-label="신호 고르기"
          onValueChange={v => v && setParams(prev => { const n = new URLSearchParams(prev); if (v === "confirm") n.set("era_signal", v); else n.delete("era_signal"); return n }, { replace: true, preventScrollReset: true })}>
          <ToggleGroupItem value="warn" className="px-3 text-caption">경계 {s.warn.episodes.length}번</ToggleGroupItem>
          <ToggleGroupItem value="confirm" className="px-3 text-caption">확정 {s.confirm.episodes.length}번</ToggleGroupItem>
        </ToggleGroup>
      </div>
      <EpisodePaths signal={s[which]} current={s[which].on ? s.current_path : undefined} compact={compact} />
    </div>
    {!compact && <p className="text-caption text-muted-foreground">참고: 12개월 수익률 <span className="tabular-nums">{formatPercent(s.reference.ret_12m)}</span> · 52주 고점 대비 <span className="tabular-nums">{formatPercent(s.reference.from_52w_high)}</span>
      {s.recession_hint.inverted_24m != null && <> · 최근 24개월 안 장단기 금리 역전 {s.recession_hint.inverted_24m ? `있음(최저 ${formatPp(s.recession_hint.min_24m)})` : "없음"}</>}</p>}
  </Section>
}

/** 금리 경보 게이지 — 인플레이션형은 급등, 디스인플레이션형은 급락이 경보 쪽 (pipeline/era.py 규칙과 같은 문턱) */
function RateGauges({ m }: { m: EraStateResponse["meaning"] }) {
  const sign = m.regime === "disinflation" ? -1 : 1
  const rows = [
    { label: "10년 금리 6개월 변화", v: m.rate_change_6m.us10y, th: 0.75 },
    { label: "3개월 금리 6개월 변화", v: m.rate_change_6m.bill3m, th: 1.0 },
  ]
  return <div className="space-y-3">
    {rows.map(r => <div key={r.label} className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">{r.label}</span>
        <span className="font-mono tabular-nums">{formatPp(r.v)} / 경보 {formatPp(sign * r.th)}</span>
      </div>
      <Progress value={r.v == null ? 0 : Math.max(0, Math.min(100, (sign * r.v / r.th) * 100))} aria-label={`${r.label} 경보까지`}
        className={cn("h-2 rounded-none", m.conditional_flag ? "[&>[data-slot=progress-indicator]]:bg-up" : "[&>[data-slot=progress-indicator]]:bg-hypothesis")} />
    </div>)}
  </div>
}

function MeaningSection({ data, regimes, compact }: { data: EraStateResponse; regimes?: RegimesResponse; compact?: boolean }) {
  const m = data.meaning
  const series = useMemo<RegimeSeries[]>(() => [{ key: "corr", label: "주식–금리 상관(36개월)", color: "--chart-4",
    data: m.corr_series.map(([time, value]) => ({ time, value })) }], [m.corr_series])
  const bands = useMemo<RegimeBandSpec[]>(() => [
    ...(regimes?.recessions ?? []).map(r => ({ start: r.start, end: r.end, color: "--chart-gray", title: `NBER 침체 ${r.start} ~ ${r.end}` })),
    ...(regimes?.phases ?? []).filter(p => p.kind === "bear").map(p => ({ start: p.start, end: p.end, color: "--down", faint: p.provisional, title: `약세장 ${p.start} ~ ${p.end}` })),
  ], [regimes])
  const inflation = m.regime === "inflation"
  return <Section id="now-meaning" step={2} title={compact ? "금리의 뜻" : "금리는 지금 무슨 뜻인가"}
    how={<>같은 '금리 상승'도 시대에 따라 뜻이 반대입니다. 주식과 금리가 반대로 움직이는 시기(상관 &lt; 0)엔 금리 급등이 악재였고, 같이 움직이는 시기(상관 &gt; 0)엔 금리 급락·인하가 위기 신호였습니다(2001·2008). 그래서 지금이 어느 쪽인지 보고, 그 쪽의 위험 방향만 경보로 씁니다.</>}>
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant="outline" className={cn("font-medium", inflation ? "border-hypothesis/40 bg-hypothesis/10 text-hypothesis" : "border-down/40 text-down-ink")}>{inflation ? "인플레이션형" : "디스인플레이션형"}</Badge>
      <span>{compact ? "상관" : "주식–금리 상관"} 36개월 <b className="tabular-nums">{m.corr_36m?.toFixed(2) ?? "-"}</b>{!compact && <> · 250일 <b className="tabular-nums">{m.corr_250d?.toFixed(2) ?? "-"}</b></>}
        {m.cpi_yoy != null && <> · CPI {compact ? "" : "전년비 "}<span className="tabular-nums">{m.cpi_yoy.toFixed(2)}%</span>{!compact && ` (${m.cpi_month})`}</>}</span>
      {!compact && <Badge variant="outline" className={cn("font-normal", m.conditional_flag ? "border-up/40 text-up-ink" : "text-muted-foreground")}>경보 {m.conditional_flag ? "켜짐" : "꺼짐"}</Badge>}
    </div>
    {compact ? <RateGauges m={m} /> : <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="min-w-0 space-y-3">
        <div className="flex items-center gap-1 text-caption text-muted-foreground">
          주식–금리 상관(36개월) · 음영 = 약세장·침체
          <InfoTip label="상관 시계열 읽는 법">0 위 = 디스인플레이션형(금리↓ 주식↓) · 0 아래 = 인플레이션형(금리↑ 주식↓). 하워드 막스가 말한 'Sea Change'가 이 상관의 부호로 관측됩니다.</InfoTip>
        </div>
        <RegimeChart series={series} bands={bands} height={220} zeroLine formatValue={v => v.toFixed(2)} />
        <div className="space-y-1.5">
          <p className="text-sm font-medium">연대별 상관</p>
          <div className="grid grid-cols-4 gap-1 sm:grid-cols-7">
            {Object.entries(m.decades).map(([k, v]) => <div key={k} className="bg-muted/60 px-2 py-1.5 text-center">
              <div className="text-caption text-muted-foreground">{k}</div>
              <div className="font-mono text-sm tabular-nums">{v > 0 ? "+" : ""}{v.toFixed(2)}</div>
            </div>)}
          </div>
        </div>
      </div>
      <div className="min-w-0 space-y-3">
        <p className="text-sm font-medium">{inflation ? "인플레이션형 경보 — 금리 급등이 위험 신호" : "디스인플레이션형 경보 — 금리 급락이 위험 신호"}</p>
        <RateGauges m={m} />
        <div className="space-y-1 border border-hypothesis/30 bg-hypothesis/5 px-3 py-2.5 text-sm">
          <p className="font-medium text-hypothesis">{m.research.note}</p>
          <p className="tabular-nums">{m.research.a}</p>
          <p className="tabular-nums">{m.research.b}</p>
        </div>
      </div>
    </div>}
  </Section>
}

function TemperatureSection({ data, compact }: { data: EraStateResponse; compact?: boolean }) {
  const t = data.temperature
  const setCheck = useSetEraCheck()
  return <Section id="now-temp" step={3} title={compact ? "막스식 온도" : "막스식 온도 — 지금 어디쯤인가"}
    how={<>하워드 막스는 "어디로 갈지는 몰라도 지금 어디에 있는지는 알아야 한다"고 말합니다. 여러 관측을 모아 '증거의 우세'를 봅니다. 대부분의 시기는 '균형'이 정상이고, 차이가 3 이상 벌어질 때만 한쪽 우세로 봅니다. 숫자 항목은 자동, 분위기 항목은 직접 판단해 기록합니다.</>}>
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant="outline" className={cn("font-normal", t.verdict === "hot" ? HEAT.hot.cls : t.verdict === "cold" ? HEAT.cold.cls : "")}>{VERDICT[t.verdict]}</Badge>
      <span>뜨거움 {t.hot} · 보통 {t.normal} · 차가움 {t.cold}</span>
    </div>
    <div className={cn("grid gap-6", !compact && "@[1180px]/market:grid-cols-2")}>
      <div className="min-w-0 space-y-1.5">
        {!compact && <p className="flex items-center gap-1 text-sm font-medium">숫자로 보는 {t.items.length}개
          {t.missing.length > 0 && <InfoTip label="아직 수집하지 않는 항목">아직 수집하지 않는 항목: {t.missing.join(" · ")}. 이 온도는 막스 체크리스트의 일부만 봅니다.</InfoTip>}</p>}
        <Table>
          <TableBody>{t.items.map(i => <TableRow key={i.key}>
            <TableCell className="w-[45%] whitespace-normal text-sm md:w-auto md:min-w-[11rem]" title={i.source}>{i.label}</TableCell>
            {!compact && <TableCell className="whitespace-normal text-caption text-muted-foreground max-md:hidden">{i.basis}</TableCell>}
            <TableCell className="text-right font-mono tabular-nums">{i.value ?? "-"}{typeof i.value === "number" ? ` ${i.unit}`.replace(" %", "%") : ""}</TableCell>
            <TableCell className="w-16 text-right"><Badge variant="outline" className={cn("font-normal", HEAT[i.state].cls)}>{HEAT[i.state].label}</Badge></TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </div>
      {!compact && <div className="min-w-0 space-y-1.5">
        <p className="text-sm font-medium">분위기 · 직접 판단</p>
        {t.judged.map(j => <div key={j.key} className="flex flex-wrap items-center justify-between gap-2 border-b py-1.5 last:border-0">
          <span className="min-w-0 flex-1 text-sm">{j.label}</span>
          <ToggleGroup type="single" size="sm" variant="outline" value={j.state ?? ""} aria-label={j.label}
            onValueChange={v => setCheck.mutate({ key: j.key, state: (v || null) as EraHeat | null }, { onError: () => toast.error("저장하지 못했습니다.") })}>
            {(["cold", "normal", "hot"] as const).map(k => <ToggleGroupItem key={k} value={k} className="px-2.5 text-caption">{HEAT[k].label}</ToggleGroupItem>)}
          </ToggleGroup>
        </div>)}
      </div>}
    </div>
  </Section>
}

/** '누가' — 사람은 인물 상세 링크(대표 이름), 기관·인물 엔티티가 없는 이름은 텍스트(ia-redesign §4.23 연결 지점 3) */
function Who({ p }: { p: EraPremise }) {
  if (!p.who_people?.length) return <>{p.who}</>
  return <>{p.who_people.map((w, i) => <span key={w.label}>{i > 0 && " · "}{w.kind === "person" && w.entity_id
    ? <Link to={personPath(w.entity_id)} className="hover:text-foreground hover:underline">{w.name ?? w.label}</Link> : w.label}</span>)}</>
}

function PremiseSection({ data }: { data: EraStateResponse }) {
  return <Section id="now-premises" step={4} title="구루 전제 원장 — 누구의 전제가 맞아 가는가"
    how={<>구루들의 시대 진단을 '반증할 수 있는 지표'와 한 쌍으로 적었습니다. '지지'는 지금 숫자가 그 전제와 맞는다는 뜻이지 전제가 증명됐다는 뜻이 아닙니다. 시점이 없는 전제(언젠가 위기가 온다)는 맞았는지 셀 수 없어 '반증 불가'로 둡니다.</>}>
    <Table>
      <TableHeader><TableRow>
        <TableHead className="w-24">판정</TableHead><TableHead>전제</TableHead><TableHead className="max-md:hidden">지금 숫자</TableHead><TableHead className="max-lg:hidden">판정 규칙</TableHead>
      </TableRow></TableHeader>
      <TableBody>{data.premises.map(p => {
        const st = PREMISE[p.status ?? "none"]
        return <TableRow key={p.key} className="align-top">
          <TableCell><Badge variant="outline" className={cn("font-normal", st.cls)}>{st.label}</Badge></TableCell>
          <TableCell className="whitespace-normal">
            <p className="text-sm font-medium leading-snug">{p.claim}</p>
            <p className="mt-0.5 text-caption text-muted-foreground"><Who p={p} /> · {p.kind}
              {p.sources.map(s => <span key={s.title}> · {s.doc_id ? <Link to={`/doc/${s.doc_id}`} className="hover:text-foreground hover:underline">{s.title}</Link>
                : <a href={s.url ?? "#"} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 hover:text-foreground hover:underline">{s.title}<ExternalLink className="size-3" aria-hidden="true" /></a>}</span>)}
            </p>
          </TableCell>
          <TableCell className="whitespace-normal text-sm tabular-nums max-md:hidden">{p.evidence.map(e => <div key={e}>{e}</div>)}</TableCell>
          <TableCell className="whitespace-normal text-caption text-muted-foreground max-lg:hidden">{p.rule}</TableCell>
        </TableRow>
      })}</TableBody>
    </Table>
    {data.latest_memos.length > 0 && <div className="space-y-1">
      <p className="text-sm font-medium">최근 메모 · Howard Marks</p>
      <ul className="divide-y border-y text-sm">{data.latest_memos.map(m => <li key={m.doc_id} className="flex gap-3 py-1.5">
        <span className="font-mono text-caption tabular-nums text-muted-foreground">{m.date}</span>
        <Link to={`/doc/${m.doc_id}`} className="hover:underline">{m.title}</Link>
      </li>)}</ul>
    </div>}
  </Section>
}

/** 모바일 4·5 — 구루 전제 한 줄 + 프라이싱 4건, 나머지는 전체 화면으로 */
function PremisePricingCompact({ data }: { data?: EraStateResponse }) {
  const count = (s: string) => data?.premises.filter(p => p.status === s).length ?? 0
  return <Section id="now-pricing" step="4·5" title="전제와 프라이싱">
    <span id="now-premises" className="sr-only">구루 전제</span>
    {data && <p className="text-sm">구루 전제 지지 {count("supports")} · 반증 쪽 {count("challenges")} · 판정 밖 {count("untestable") + count("nodata")}</p>}
    <PricingCompact />
  </Section>
}
