import { useMemo } from "react"
import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { BookOpen, ExternalLink, Sparkles } from "lucide-react"
import { toast } from "sonner"
import RegimeChart from "@/components/charts/RegimeChart"
import type { RegimeBandSpec, RegimeSeries } from "@/components/charts/RegimeChart"
import { ErrorState } from "@/components/shared/ErrorState"
import { Markdown } from "@/components/shared/Markdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useEraCommentary, useEraState, useGenerateCommentary, useSetEraCheck } from "@/hooks/useRegimes"
import { cn } from "@/lib/utils"
import { formatKstDateTime, formatPercent, formatPp } from "@/utils/format"
import type { EraHeat, EraLayerState, EraPremise, EraStateResponse, RegimesResponse } from "@/types"
import { EpisodePaths } from "./EpisodePaths"

const HEAT: Record<EraHeat, { label: string; cls: string }> = {
  hot: { label: "뜨거움", cls: "border-up/40 text-up" },
  normal: { label: "보통", cls: "text-muted-foreground" },
  cold: { label: "차가움", cls: "border-down/40 text-down" },
}
const PREMISE: Record<NonNullable<EraPremise["status"]> | "none", { label: string; cls: string }> = {
  supports: { label: "지지", cls: "border-chart-profit/50 text-chart-profit-dark" },
  challenges: { label: "반증 쪽", cls: "border-up/40 text-up" },
  mixed: { label: "엇갈림", cls: "border-chart-warning/50 text-hypothesis" },
  untestable: { label: "반증 불가", cls: "text-muted-foreground" },
  nodata: { label: "데이터 없음", cls: "text-muted-foreground" },
  none: { label: "판정 불가", cls: "text-muted-foreground" },
}

/** 섹션 머리 + '읽는 법' — 투자자가 숫자 전에 무엇을 보는지부터 알게 */
function Section({ id, step, title, how, children }: { id: string; step: number; title: string; how: ReactNode; children: ReactNode }) {
  return <Card id={id} className="scroll-mt-24">
    <CardHeader className="space-y-2">
      <CardTitle className="flex items-baseline gap-2"><span className="text-caption tabular-nums text-muted-foreground">{step}</span>{title}</CardTitle>
      <div className="flex gap-2 rounded-lg bg-muted/50 px-3 py-2 text-caption leading-relaxed text-muted-foreground">
        <BookOpen className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /><div><span className="font-medium text-foreground">읽는 법 </span>{how}</div>
      </div>
    </CardHeader>
    <CardContent className="space-y-4">{children}</CardContent>
  </Card>
}

const Light = ({ on }: { on: boolean }) => <span className={cn("inline-block size-2.5 shrink-0 rounded-full", on ? "bg-down" : "bg-muted-foreground/30")} aria-hidden="true" />

/**
 * 지금 시장 읽기(docs/specs/market-regimes.md §8) — 요약 4칸 · AI 해설 · 층 1~4.
 * 판정은 서버 규칙(pipeline/era.py), AI 해설은 그 결과를 문장으로 옮길 뿐이다.
 */
export function NowPanel({ regimes }: { regimes?: RegimesResponse }) {
  const q = useEraState()
  if (q.isPending) return <div className="space-y-4"><Skeleton className="h-28 w-full rounded-xl" /><Skeleton className="h-64 w-full rounded-xl" /></div>
  if (q.isError) return <ErrorState message="지금 시장 판정을 불러오지 못했습니다." onRetry={() => void q.refetch()} />
  const d = q.data
  return <div className="space-y-6">
    <Summary data={d} />
    <Commentary />
    {d.state.available && <StateSection data={d} />}
    {d.meaning.available && <MeaningSection data={d} regimes={regimes} />}
    <TemperatureSection data={d} />
    <PremiseSection data={d} />
  </div>
}

function Summary({ data }: { data: EraStateResponse }) {
  const { state, meaning, temperature: t, premises } = data
  const count = (s: string) => premises.filter(p => p.status === s).length
  const tiles = [
    { href: "#now-state", label: "1 추세가 꺾였나", value: !state.available ? "-" : STAGE[state.stage].label,
      sub: state.available ? `경계 ${state.warn.on ? "켜짐" : "꺼짐"} · 확정 ${state.confirm.on ? "켜짐" : "꺼짐"}` : "", warn: state.available && state.stage !== "none" },
    { href: "#now-meaning", label: "2 금리는 무슨 뜻인가", value: meaning.regime === "inflation" ? "인플레이션형" : meaning.regime === "disinflation" ? "디스인플레이션형" : "-",
      sub: meaning.regime === "inflation" ? "금리 급등이 위험 신호" : meaning.regime === "disinflation" ? "금리 급락이 위험 신호" : "", warn: meaning.conditional_flag },
    { href: "#now-temp", label: "3 막스식 온도", value: t.verdict === "hot" ? "뜨거움 우세" : t.verdict === "cold" ? "차가움 우세" : "균형",
      sub: `뜨거움 ${t.hot} · 차가움 ${t.cold} · 보통 ${t.normal}`, warn: t.verdict === "hot" },
    { href: "#now-premises", label: "4 구루 전제", value: `지지 ${count("supports")}`, sub: `엇갈림 ${count("mixed")} · 반증 쪽 ${count("challenges")} · 판정 밖 ${count("untestable") + count("nodata")}`, warn: false },
  ]
  return <div className="space-y-2">
    <h3 className="text-base font-semibold">지금 시장은</h3>
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {tiles.map(x => <a key={x.href} href={x.href} className="rounded-xl border bg-card px-4 py-3 transition-colors hover:bg-muted/50">
        <div className="text-caption text-muted-foreground">{x.label}</div>
        <div className={cn("mt-0.5 text-lg font-semibold", x.warn && "text-up")}>{x.value}</div>
        <div className="text-caption text-muted-foreground">{x.sub}</div>
      </a>)}
    </div>
    <p className="text-caption text-muted-foreground">판정은 모두 정해진 규칙으로 계산합니다. 아래 AI 해설은 이 판정을 문장으로 풀어 줄 뿐, 판정을 바꾸지 않습니다.</p>
  </div>
}

function Commentary() {
  const q = useEraCommentary()
  const gen = useGenerateCommentary()
  const c = q.data
  const run = () => gen.mutate(undefined, { onError: () => toast.error("해설을 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.") })
  return <Card className="border-hypothesis/30">
    <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
      <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-hypothesis" aria-hidden="true" />AI 해설</CardTitle>
      <div className="flex items-center gap-2 text-caption text-muted-foreground">
        {c?.created_at && <span>{formatKstDateTime(c.created_at)} · {c.model}</span>}
        {c?.body && c.stale && <Badge variant="outline" className="border-hypothesis/40 font-normal text-hypothesis">숫자가 바뀌었어요</Badge>}
        <Button size="sm" variant={c?.body && !c.stale ? "outline" : "default"} onClick={run} disabled={gen.isPending}>
          {gen.isPending ? <><Spinner className="size-3.5" />만드는 중…</> : c?.body ? "다시 만들기" : "해설 만들기"}
        </Button>
      </div>
    </CardHeader>
    <CardContent>
      {q.isPending ? <Skeleton className="h-40 w-full" />
        : q.isError ? <ErrorState message="해설을 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : gen.isPending && !c?.body ? <p className="py-6 text-sm text-muted-foreground">판정 결과와 최신 하워드 막스 메모를 읽고 해설을 쓰는 중입니다(30초~1분).</p>
        : !c?.body ? <p className="py-6 text-sm text-muted-foreground">아래 네 층의 판정 결과와 최신 하워드 막스 메모를 바탕으로, 지금 시장이 어디에 있는지를 쉬운 말로 풀어 드립니다. 숫자가 바뀐 날에만 새로 만듭니다.</p>
        : <>
          <Markdown className="text-[14px] leading-7 [&_h2]:mt-5 [&_h2]:text-[15px] [&_h2]:font-semibold [&_li]:my-1 [&_p]:my-2">{c.body.replace(/~/g, "\\~")}</Markdown>
          <p className="mt-3 text-caption text-muted-foreground">AI가 규칙 판정을 옮긴 글입니다. 예측이나 매매 권유가 아닙니다. 숫자는 아래 각 층에서 확인하세요.</p>
        </>}
    </CardContent>
  </Card>
}

const STAGE = {
  none: { label: "추세 유지", sub: "경계·확정 모두 꺼짐", cls: "" },
  warn: { label: "경계", sub: "추세 이탈 1단계", cls: "text-hypothesis" },
  confirm: { label: "확정", sub: "하락 추세 확인", cls: "text-up" },
} as const

function SignalCard({ step, sig, active, detail }: { step: string; sig: EraLayerState["warn"] | EraLayerState["confirm"]; active: boolean; detail: ReactNode }) {
  const st = sig.stats
  return <div className={cn("space-y-2 rounded-xl border px-4 py-3", active && "border-up/40 bg-up/5")}>
    <div className="flex items-center gap-2"><Light on={sig.on} /><span className="text-caption font-medium text-muted-foreground">{step}</span>
      <span className={cn("text-sm font-semibold", sig.on && "text-up")}>{sig.on ? "켜짐" : "꺼짐"}</span>
      {sig.since && <span className="text-caption text-muted-foreground">· {sig.since}부터</span>}</div>
    <p className="text-sm">{sig.label}</p>
    <div className="text-caption text-muted-foreground">{detail}</div>
    <p className="text-caption text-muted-foreground">
      1956년 이후 약세장 {st.bears_total}번 중 {st.bears_caught}번 포착 · 켜질 때 고점 대비 중앙 <b className="text-foreground">{formatPercent(st.drawdown_at_median)}</b>
      {" "}· 그 뒤 바닥까지 중앙 <b className="text-down">{formatPercent(st.remaining_median)}</b> 더 · 헛경보 10년에 {st.false_per_decade}번
    </p>
  </div>
}

function StateSection({ data }: { data: EraStateResponse }) {
  const s = data.state
  const [params, setParams] = useSearchParams()
  const which = params.get("now_sig") === "confirm" ? "confirm" : "warn"
  const stage = STAGE[s.stage]
  return <Section id="now-state" step={1} title="추세가 꺾였나 — 경계와 확정"
    how={<>하락 추세 이탈을 두 단계로 봅니다. <b>경계</b>는 월말 종가가 12개월 이동평균 아래로 내려간 것 — 빠르지만 10년에 두 번쯤 헛경보가 납니다. <b>확정</b>은 1년 신저가를 깨거나 200일선이 꺾여 내려가는 것 — 늦지만 헛경보가 드뭅니다. 매일 판정하는 이평선은 헛경보가 열 배쯤 많아서 쓰지 않습니다. 이 판정은 '바닥'이 아니라 '지금 어디쯤인가'를 말합니다. 과거엔 신호가 켜진 뒤에도 하락의 절반 이상이 남아 있었습니다.</>}>
    <p className="text-sm">지금: <span className={cn("text-base font-semibold", stage.cls)}>{stage.label}</span> <span className="text-muted-foreground">— {stage.sub}</span></p>
    <div className="grid gap-3 md:grid-cols-2">
      <SignalCard step="1단계 경계" sig={s.warn} active={s.stage === "warn"} detail={<>
        {s.warn.month_end} 월말 종가는 12개월선보다 {formatPercent(s.warn.vs_sma_pct)} · 이번 달 지금 값으로는 {formatPercent(s.warn.provisional_vs_sma_pct)}
        {s.warn.provisional_on !== s.warn.on && <Badge variant="outline" className="ml-1.5 border-hypothesis/40 font-normal text-hypothesis">월말에 바뀔 수 있음</Badge>}
      </>} />
      <SignalCard step="2단계 확정" sig={s.confirm} active={s.stage === "confirm"} detail={<>
        1년 신저가 이탈 {s.confirm.new_low ? "있음" : "없음"}{s.confirm.last_new_low && ` (마지막 ${s.confirm.last_new_low})`}
        {" "}· 200일선 20일 기울기 {formatPercent(s.confirm.ma200_slope_pct)} {s.confirm.slope_down ? "(하락)" : ""}
      </>} />
    </div>
    <p className="text-caption text-muted-foreground">참고(판정에 쓰지 않음): 12개월 수익률 {formatPercent(s.reference.ret_12m)} · 52주 고점 대비 {formatPercent(s.reference.from_52w_high)}
      {s.recession_hint.inverted_24m != null && <> · 최근 24개월 10년−3개월 금리 역전 {s.recession_hint.inverted_24m ? `있음(최저 ${formatPp(s.recession_hint.min_24m)})` : "없음"} — 역전 이력이 있을 때 켜지면 경기침체형 약세일 가능성이 높았습니다</>}</p>
    <div className="space-y-2 border-t pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">과거에 켜졌을 때, 이후 1년은 어떻게 흘렀나</p>
        <ToggleGroup type="single" size="sm" variant="outline" value={which} aria-label="신호 고르기"
          onValueChange={v => v && setParams(prev => { const n = new URLSearchParams(prev); if (v === "confirm") n.set("now_sig", v); else n.delete("now_sig"); return n }, { replace: true })}>
          <ToggleGroupItem value="warn" className="px-3 text-caption">경계 {s.warn.episodes.length}번</ToggleGroupItem>
          <ToggleGroupItem value="confirm" className="px-3 text-caption">확정 {s.confirm.episodes.length}번</ToggleGroupItem>
        </ToggleGroup>
      </div>
      <EpisodePaths signal={s[which]} current={s[which].on ? s.current_path : undefined} />
    </div>
  </Section>
}

function MeaningSection({ data, regimes }: { data: EraStateResponse; regimes?: RegimesResponse }) {
  const m = data.meaning
  const series = useMemo<RegimeSeries[]>(() => [{ key: "corr", label: "주식–금리 상관(36개월)", color: "--chart-4",
    data: m.corr_series.map(([time, value]) => ({ time, value })) }], [m.corr_series])
  const bands = useMemo<RegimeBandSpec[]>(() => (regimes?.phases ?? []).filter(p => p.kind === "bear")
    .map(p => ({ start: p.start, end: p.end, color: "--down", faint: p.provisional, title: `약세장 ${p.start} ~ ${p.end}` })), [regimes])
  const inflation = m.regime === "inflation"
  return <Section id="now-meaning" step={2} title="금리는 지금 무슨 뜻인가"
    how={<>같은 '금리 상승'도 시대에 따라 뜻이 반대입니다. 주식과 금리가 반대로 움직이는 시기(상관 &lt; 0)엔 금리 급등이 주식에 악재였고, 같이 움직이는 시기(상관 &gt; 0)엔 금리 급락·인하가 위기 신호였습니다(2001·2008). 그래서 먼저 지금이 어느 쪽인지 보고, 그 쪽의 위험 방향만 경보로 씁니다. 하워드 막스가 말한 'Sea Change'가 이 상관의 부호로 관측됩니다.</>}>
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline" className={cn("px-2.5 py-1 text-sm font-medium", inflation ? "border-up/40 text-up" : "border-down/40 text-down")}>{inflation ? "인플레이션형" : "디스인플레이션형"}</Badge>
      <span className="text-sm text-muted-foreground">상관 36개월 <b className="tabular-nums text-foreground">{m.corr_36m?.toFixed(2)}</b> · 최근 250일 <b className="tabular-nums text-foreground">{m.corr_250d?.toFixed(2)}</b>
        {m.cpi_yoy != null && <> · CPI 전년비 <b className="tabular-nums text-foreground">{m.cpi_yoy.toFixed(1)}%</b>({m.cpi_month})</>}</span>
    </div>
    <RegimeChart series={series} bands={bands} height={220} zeroLine formatValue={v => v.toFixed(2)} />
    <p className="text-caption text-muted-foreground">10년대 평균: {Object.entries(m.decades).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v.toFixed(2)}`).join(" · ")} — 2000·2010년대만 양(+)이었습니다. 음영은 S&P500 약세장.</p>
    <div className="rounded-lg border px-3 py-2.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Light on={m.conditional_flag} /><span className="font-medium">금리 경보 {m.conditional_flag ? "켜짐" : "꺼짐"}</span>
        <Badge variant="outline" className="border-hypothesis/40 font-normal text-hypothesis">가설</Badge>
      </div>
      <p className="mt-1 text-caption text-muted-foreground">{m.rule}. 지금 6개월 변화: 10년 {formatPp(m.rate_change_6m.us10y)} · 3개월 {formatPp(m.rate_change_6m.bill3m)}.</p>
      <p className="mt-1 text-caption text-muted-foreground">과거 성적 — {m.research.a} · {m.research.b}. {m.research.note}이라 앞으로의 관측으로 확인해야 합니다.</p>
    </div>
  </Section>
}

function TemperatureSection({ data }: { data: EraStateResponse }) {
  const t = data.temperature
  const setCheck = useSetEraCheck()
  return <Section id="now-temp" step={3} title="막스식 온도 — 지금 어디쯤인가"
    how={<>하워드 막스는 "어디로 갈지는 몰라도 지금 어디에 있는지는 알아야 한다"고 말합니다. 신호 하나로 판단하지 않고 여러 관측을 모아 '증거의 우세'를 봅니다. 대부분의 시기는 '균형'이 정상이고, 뜨거움이나 차가움이 한쪽으로 크게 기울 때만 의미가 있습니다. 숫자 항목은 자동, 분위기 항목은 직접 판단해 기록합니다.</>}>
    <p className="text-sm"><span className="font-semibold">{t.verdict === "hot" ? "뜨거움 우세" : t.verdict === "cold" ? "차가움 우세" : "균형"}</span>
      <span className="text-muted-foreground"> — 뜨거움 {t.hot} · 차가움 {t.cold} · 보통 {t.normal} (차이가 3 이상이면 한쪽 우세)</span></p>
    <Table>
      <TableHeader><TableRow><TableHead>항목</TableHead><TableHead className="text-right">지금</TableHead><TableHead>판정</TableHead><TableHead className="max-md:hidden">기준</TableHead></TableRow></TableHeader>
      <TableBody>{t.items.map(i => <TableRow key={i.key}>
        <TableCell className="text-sm">{i.label}<div className="text-[11px] text-muted-foreground">{i.source}</div></TableCell>
        <TableCell className="text-right tabular-nums">{i.value ?? "-"}{typeof i.value === "number" ? i.unit : ""}</TableCell>
        <TableCell><Badge variant="outline" className={cn("font-normal", HEAT[i.state].cls)}>{HEAT[i.state].label}</Badge></TableCell>
        <TableCell className="text-caption text-muted-foreground max-md:hidden">{i.basis}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    <div className="space-y-2">
      <p className="text-sm font-medium">분위기·행동 — 직접 판단</p>
      {t.judged.map(j => <div key={j.key} className="flex flex-wrap items-center justify-between gap-2 border-b py-1.5 last:border-0">
        <span className="min-w-0 flex-1 text-sm">{j.label}</span>
        <ToggleGroup type="single" size="sm" variant="outline" value={j.state ?? ""} aria-label={j.label}
          onValueChange={v => setCheck.mutate({ key: j.key, state: (v || null) as EraHeat | null }, { onError: () => toast.error("저장하지 못했습니다.") })}>
          {(["cold", "normal", "hot"] as const).map(k => <ToggleGroupItem key={k} value={k} className="px-2.5 text-caption">{HEAT[k].label}</ToggleGroupItem>)}
        </ToggleGroup>
      </div>)}
    </div>
    <p className="text-caption text-muted-foreground">아직 수집하지 않는 항목: {t.missing.join(" · ")}. 이 온도는 막스 체크리스트의 일부만 봅니다.</p>
  </Section>
}

function PremiseSection({ data }: { data: EraStateResponse }) {
  return <Section id="now-premises" step={4} title="구루 전제 원장 — 누구의 전제가 맞아 가는가"
    how={<>구루들의 시대 진단을 '반증할 수 있는 지표'와 한 쌍으로 적었습니다. '지지'는 지금 숫자가 그 전제와 맞는다는 뜻이지 전제가 증명됐다는 뜻이 아닙니다. 시점이 없는 전제(언젠가 위기가 온다)는 맞았는지 셀 수 없어 '반증 불가'로 둡니다.</>}>
    <div className="grid gap-3 lg:grid-cols-2">
      {data.premises.map(p => {
        const st = PREMISE[p.status ?? "none"]
        return <div key={p.key} className="space-y-2 rounded-xl border px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-medium leading-snug">{p.claim}</p>
            <Badge variant="outline" className={cn("shrink-0 font-normal", st.cls)}>{st.label}</Badge>
          </div>
          <p className="text-caption text-muted-foreground">{p.who} · <span className={p.kind === "공유" ? "text-foreground" : ""}>{p.kind === "공유" ? "구루들이 공유하는 전제" : p.kind === "분기" ? "구루들끼리 갈리는 전제" : p.kind}</span></p>
          {p.evidence.length > 0 && <div className="flex flex-wrap gap-1.5">{p.evidence.map(e => <Badge key={e} variant="secondary" className="font-normal tabular-nums">{e}</Badge>)}</div>}
          <p className="text-caption text-muted-foreground">판정 규칙: {p.rule}</p>
          {p.sources.length > 0 && <div className="flex flex-wrap gap-x-3 gap-y-1 text-caption">
            {p.sources.map(s => s.doc_id ? <Link key={s.title} to={`/doc/${s.doc_id}`} className="text-primary hover:underline">{s.title} <span className="text-muted-foreground">{s.date}</span></Link>
              : <a key={s.title} href={s.url ?? "#"} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">{s.title}<ExternalLink className="size-3" aria-hidden="true" /> <span className="text-muted-foreground">{s.date}</span></a>)}
          </div>}
        </div>
      })}
    </div>
    {data.latest_memos.length > 0 && <p className="text-caption text-muted-foreground">
      최근 하워드 막스 메모: {data.latest_memos.map((m, i) => <span key={m.doc_id}>{i > 0 && " · "}<Link to={`/doc/${m.doc_id}`} className="text-primary hover:underline">{m.title}</Link> {m.date}</span>)}
    </p>}
  </Section>
}

