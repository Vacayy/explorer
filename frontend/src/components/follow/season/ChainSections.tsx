// 콜 상세의 실적 체인 섹션 — 발표 전 → 컨콜 → 시장 반응 → 그 뒤 (docs/specs/earnings-season.md §콜 상세)
// 데이터는 GET /chain/{id} 하나. 정성(기대·반응 구조화)이 없으면 칸마다 '없음'의 이유를 쓴다(Partial).
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { Bar, BarChart, Cell, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Badge } from "@/components/ui/badge"
import { InfoTip } from "@/components/shared/InfoTip"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { usePinCore, useSeason } from "@/hooks/useTranscripts"
import { formatPercent } from "@/utils/format"
import { cn } from "@/lib/utils"
import { Bullets, Cols, H3, Meta, Pp, SHORT_REASON, Section, VERDICT, VERDICT_CLS, WEIGHT, mmdd } from "@/components/follow/season/seasonUi"
import type { ChainDetail, ExpectationIssue, ReactionGrade } from "@/types"

const TOOLTIP_STYLE = { fontSize: 12, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" }
const CHART_MARGIN = { top: 18, right: 12, bottom: 0, left: 0 }
/** 근거 번호([39][13])는 이 화면에 출처 목록이 없어 지운다 — 전문·출처는 아래 펼치기 */
const clean = (s: string) => s.replace(/\s*\[\d+\]/g, "").trim()
const FOLLOW: Record<string, string> = { 유지: "유지됐다", 확대: "더 커졌다", 되돌림: "되돌려졌다", 반전: "뒤집혔다" }
const DROVE: Record<string, string> = { major: "주가를 크게 움직임", minor: "일부 영향", none: "영향 없음" }

/* ---------- 헤더: 섹터 링크 + 핵심 표시·고정 ---------- */
export function ChainHeaderLinks({ chain }: { chain: ChainDetail }) {
  const season = useSeason()
  const pin = usePinCore()
  const core = season.data?.core.tickers.find((t) => t.ticker === chain.ticker)
  const pinned = !!core?.reasons.includes("pinned")
  const criteria = season.data?.core.criteria
  const toggle = () => pin.mutate({ ticker: chain.ticker, pinned: !pinned }, {
    onSuccess: () => toast.success(pinned ? `${chain.ticker} 핵심 고정을 풀었습니다` : `${chain.ticker}를 핵심으로 고정했습니다`),
    onError: (e) => toast.error(e.message),
  })
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Link to={`/follow/transcripts?view=season&sector=${encodeURIComponent(chain.sector)}`} className="text-xs text-primary hover:underline whitespace-nowrap"
        title="이 섹터의 이번 시즌 반응 보기">{chain.sector_name} ›</Link>
      {core && (
        <Badge variant="outline" 
          title={criteria ? core.reasons.map((r) => criteria[r]).join(" · ") : undefined}>
          핵심 · {core.reasons.map((r) => SHORT_REASON[r]).join("·")}
        </Badge>
      )}
      {season.data && (
        <Button variant="ghost" size="xs" onClick={toggle} disabled={pin.isPending}
          title="핵심 종목은 발표 전 기대(D-7·D-1)와 시장 반응 정리가 자동으로 만들어집니다">
          {pin.isPending && <Spinner className="size-3" />}{pinned ? "고정 해제" : "핵심 고정"}
        </Button>
      )}
    </span>
  )
}

/* ---------- 같은 날짜 축의 작은 차트 묶음: 주가 · 거래량 · 내 자료 언급 ---------- */
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`

export function ChainCharts({ chain }: { chain: ChainDetail }) {
  const { series, mentions, event_date: ev } = chain
  if (!series.length) return <Meta>시세가 아직 없습니다.</Meta>

  // 언급량은 'MM-DD'(한국 시각) — 발표일 연도로 붙이고, 반년 넘게 어긋나면 전년
  const year = Number((ev ?? series[0].date).slice(0, 4))
  const evMonth = Number((ev ?? series[0].date).slice(5, 7))
  const yearOf = (mm: number) => (mm - evMonth > 6 ? year - 1 : evMonth - mm > 6 ? year + 1 : year)
  const menIso = new Map(mentions.map((m) => [`${yearOf(Number(m.day.slice(0, 2)))}-${m.day}`, m.n]))
  const byDate = new Map(series.map((s) => [s.date, s]))
  const first = [series[0].date, ...menIso.keys()].sort()[0]
  const last = [series[series.length - 1].date, ...menIso.keys()].sort().slice(-1)[0]
  // 달력일 축 — 주말은 시세가 비고(선은 이어 그림) 언급량만 있다
  const rows: { day: string; ret: number | null; bench: number | null; vol: number | null; men: number | null; after: boolean }[] = []
  for (let d = new Date(first + "T00:00:00"); isoDay(d) <= last; d.setDate(d.getDate() + 1)) {
    const day = isoDay(d), s = byDate.get(day)
    rows.push({ day, ret: s?.ret ?? null, bench: s?.bench ?? null, vol: s?.volume != null ? s.volume / 1e6 : null, men: menIso.get(day) ?? null, after: !!ev && day >= ev })
  }
  const pre = series.filter((s) => s.offset < 0 && s.volume != null)
  const preAvg = pre.length ? pre.reduce((n, s) => n + s.volume!, 0) / pre.length / 1e6 : null
  const hasVol = rows.some((r) => r.vol != null)
  const hasMen = rows.some((r) => r.men != null)
  const evInAxis = !!ev && ev >= first && ev <= last
  const band = evInAxis && <ReferenceArea x1={ev!} x2={last} fill="var(--primary)" fillOpacity={0.06} ifOverflow="visible" />
  const evLine = (label?: string) => evInAxis && <ReferenceLine x={ev!} stroke="var(--primary)" strokeDasharray="3 3"
    label={label ? { value: label, position: "insideTopLeft", fontSize: 11, fontWeight: 600, fill: "var(--foreground)" } : undefined} />
  const xAxis = (show: boolean) => <XAxis dataKey="day" hide={!show} tick={AXIS_TICK} tickFormatter={(d: string) => mmdd(d)} minTickGap={28} />
  const title = (t: string) => <p className="text-caption font-semibold">{t}</p>

  return (
    <div className="space-y-1">
      {title("주가 (발표 전 마지막 거래일 = 0, 누적 %)")}
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={rows} syncId="chain" margin={CHART_MARGIN}>
          {band}{evLine(ev ? `발표 ${mmdd(ev)}` : undefined)}
          {xAxis(false)}
          <YAxis tick={AXIS_TICK} width={40} domain={["auto", "auto"]} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}`} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(d) => mmdd(String(d))} formatter={(v) => formatPercent(Number(v))} />
          <Line dataKey="bench" name={chain.etf} stroke="var(--series)" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls isAnimationActive={false} />
          <Line dataKey="ret" name={chain.ticker} stroke="var(--foreground)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      {hasVol && <>
        {title("거래량 (백만 주)")}
        <ResponsiveContainer width="100%" height={110}>
          <BarChart data={rows} syncId="chain" margin={CHART_MARGIN}>
            {band}{evLine()}
            {xAxis(false)}
            <YAxis tick={AXIS_TICK} width={40} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(d) => mmdd(String(d))} formatter={(v) => [`${Number(v).toFixed(1)}백만 주`, "거래량"]} />
            <Bar dataKey="vol" radius={2} isAnimationActive={false}>
              {rows.map((r) => <Cell key={r.day} fill={r.after ? "var(--primary)" : "var(--muted-foreground)"} fillOpacity={r.after ? 0.85 : 0.35} />)}
            </Bar>
            {preAvg != null && <ReferenceLine y={preAvg} stroke="var(--foreground)" strokeDasharray="2 3"
              label={{ value: `발표 전 평균 ${preAvg.toFixed(0)}`, position: "insideTopLeft", fontSize: 11, fontWeight: 600, fill: "var(--foreground)" }} />}
          </BarChart>
        </ResponsiveContainer>
      </>}
      {title(hasMen ? "내 자료 언급 (건/일, 한국 시각)" : "내 자료 언급 — 이 기간 자료 없음")}
      <ResponsiveContainer width="100%" height={hasMen ? 110 : 28}>
        <BarChart data={rows} syncId="chain" margin={{ ...CHART_MARGIN, top: hasMen ? 18 : 0 }}>
          {hasMen && band}{hasMen && evLine()}
          {xAxis(true)}
          <YAxis tick={hasMen ? AXIS_TICK : false} axisLine={hasMen} tickLine={hasMen} width={40} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(d) => mmdd(String(d))} formatter={(v) => [`${v}건`, "언급"]} />
          <Bar dataKey="men" radius={2} isAnimationActive={false}>
            {rows.map((r) => <Cell key={r.day} fill={r.after ? "var(--primary)" : "var(--muted-foreground)"} fillOpacity={r.after ? 0.85 : 0.35} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-caption text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-0.5 w-4 bg-foreground" />{chain.ticker}</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block w-4 border-t-2 border-dashed border-series" />{chain.etf} (비교)</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-sm bg-muted-foreground/35" />발표 전</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-sm bg-primary/85" />발표 후</span>
      </div>
    </div>
  )
}

/* ---------- 발표 전 / 컨콜 / 시장 반응 / 그 뒤 (데스크톱 2×2) ---------- */
export function StagesCard({ chain, transcriptId }: { chain: ChainDetail; transcriptId: number }) {
  const ex = chain.expectation
  const rm = chain.reaction_meta
  const h = chain.history.find((r) => r.transcript_id === transcriptId) ?? chain.history[0]

  const before = ex?.points?.length ? <Bullets lead items={ex.points.map(clean)} />
    : ex?.positioning ? <Bullets items={[clean(ex.positioning)]} />
    : <>
      <Meta>발표 전 기대 정리가 없습니다.</Meta>
      {ex?.quant && <QuantFacts q={ex.quant} />}
    </>

  const after: ReactNode[] = []
  if (h?.d1 != null) {
    after.push(<>{h.follow ? `첫 반응이 ${FOLLOW[h.follow] ?? h.follow}` : "첫 반응"} — {chain.etf} 대비 첫 거래일 <Pp v={h.d1} />
      {h.d7 != null && <> → 일주일 <Pp v={h.d7} /></>}{h.d30 != null && <> · 한 달 <Pp v={h.d30} /></>}</>)
  }
  const pt = chain.pt_after
  if (pt && pt.n > 0) {
    after.push(<>발표 후 7일 목표가 변경 {pt.n}건(올림 <span className="text-up-ink">{pt.up}</span>·내림 <span className="text-down-ink">{pt.down}</span>)
      {pt.examples.length > 0 && <span className="text-muted-foreground"> · {pt.examples.slice(0, 3).join(", ")}</span>}</>)
  }

  return (
    <Section>
      <div className="grid grid-cols-1 gap-x-7 gap-y-4 md:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-1.5">
          <H3>발표 전{ex && <span className="text-caption font-normal text-muted-foreground">{ex.snapshot === "d1" ? "전날" : "일주일 전"} 정리</span>}</H3>
          {before}
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <H3>컨콜</H3>
          {rm?.call_points?.length ? <Bullets lead items={rm.call_points.map(clean)} /> : <Meta>아래 '핵심 정리'를 펼쳐 보세요.</Meta>}
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <H3>시장 반응{chain.reaction_status === "interim" && <span className="text-caption font-normal text-muted-foreground">진행 중</span>}</H3>
          {rm?.react_points?.length ? <Bullets lead items={rm.react_points.map(clean)} /> : <Meta>아래 '시장 반응 정리'에서 정리를 만드세요.</Meta>}
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <H3>그 뒤</H3>
          {after.length ? <Bullets lead items={after} /> : <Meta>첫 거래일이 아직 반영되지 않았습니다.</Meta>}
        </div>
      </div>
    </Section>
  )
}

function QuantFacts({ q }: { q: NonNullable<NonNullable<ChainDetail["expectation"]>["quant"]> }) {
  const facts: ReactNode[] = []
  if (q.eps_est != null) facts.push(<>EPS 컨센서스 ${q.eps_est.toFixed(2)}</>)
  if (q.runup30 != null) facts.push(<>30일 상승폭 {formatPercent(q.runup30)}{q.runup30_vs_etf != null && <> (업종 대비 <Pp v={q.runup30_vs_etf} />)</>}</>)
  if (q.pt30 && q.pt30.n > 0) facts.push(<>30일 목표가 변경 {q.pt30.n}건(올림 {q.pt30.up}·내림 {q.pt30.down})</>)
  if (q.implied_move != null) facts.push(<>옵션 내재 변동폭 ±{q.implied_move.toFixed(1)}%</>)
  return facts.length ? <Bullets items={facts} /> : null
}

/* ---------- 발표 전 시장이 주목한 내용 (발표 전 쟁점 채점) ---------- */
export function IssuesCard({ chain }: { chain: ChainDetail }) {
  const ex = chain.expectation
  const grades = chain.reaction_meta?.grades ?? []
  const missed = chain.reaction_meta?.missed ?? []
  const byIssue = new Map((ex?.issues ?? []).map((i) => [i.issue, i]))

  let content: ReactNode
  if (!ex) content = <Meta>발표 전 기대가 정리되지 않은 발표입니다.</Meta>
  else if (grades.length || missed.length) {
    content = <>
      {grades.map((g) => <IssueBlock key={g.issue} grade={g} issue={byIssue.get(g.issue)} />)}
      {missed.map((m) => (
        <div key={m}>
          <H3>{clean(m)} <Badge className={cn("font-normal", VERDICT_CLS.missed)}>{VERDICT.missed}</Badge></H3>
          <Meta>발표 전 정리에 없던 쟁점입니다.</Meta>
        </div>
      ))}
    </>
  } else if (ex.issues?.length) {
    // 기대는 있는데 채점 전 — 쟁점과 기준만
    content = <>
      {ex.issues.map((i) => <IssueBlock key={i.issue} issue={i} />)}
      <Meta>채점은 시장 반응 정리가 만들어지면 붙습니다.</Meta>
    </>
  } else content = <Meta>발표 전 정리에 쟁점이 없습니다.</Meta>

  return <Section title="발표 전 시장이 주목한 내용">{content}</Section>
}

function IssueBlock({ grade, issue }: { grade?: ReactionGrade; issue?: ExpectationIssue }) {
  const name = grade?.issue ?? issue?.issue ?? ""
  const weight = grade?.weight ?? issue?.weight
  const items: ReactNode[] = []
  if (issue?.good || issue?.bad) items.push(<>발표 전 기준: {issue.good && <>호재면 {issue.good}</>}{issue.good && issue.bad && " / "}{issue.bad && <>악재면 {issue.bad}</>}</>)
  if (grade?.outcome) items.push(<>컨콜: {grade.outcome}</>)
  if (grade?.drove) items.push(<>시장: <b>{DROVE[grade.drove] ?? grade.drove}</b></>)
  return (
    <div>
      <H3>
        {name}
        {weight && <Badge variant="outline" className={cn("font-normal", weight === "high" && "border-primary/40 text-primary")}>발표 전 {WEIGHT[weight]}</Badge>}
        {grade?.verdict && <Badge className={cn("font-normal", VERDICT_CLS[grade.verdict])}>{VERDICT[grade.verdict]}</Badge>}
      </H3>
      {items.length > 0 && <Bullets items={items} />}
    </div>
  )
}

/* ---------- 지난 분기와 비교 (직전 분기 체인이 있을 때만) ---------- */
export function VsPrevCard({ chain }: { chain: ChainDetail }) {
  const v = chain.reaction_meta?.vs_prev
  if (!v?.length) return null
  return <Section title="지난 분기와 비교"><Bullets lead items={v.map(clean)} /></Section>
}

/** 쟁점 카드 + 지난 분기 비교 — 비교가 있으면 2단 */
export function IssuesRow({ chain }: { chain: ChainDetail }) {
  return chain.reaction_meta?.vs_prev?.length
    ? <Cols><IssuesCard chain={chain} /><VsPrevCard chain={chain} /></Cols>
    : <IssuesCard chain={chain} />
}

/* ---------- 분기별 기록 (표는 여기 한 곳만) ---------- */
export function HistoryCard({ chain, transcriptId, onSelect }: { chain: ChainDetail; transcriptId: number; onSelect: (id: number) => void }) {
  if (!chain.history.length) return null
  return (
    <Section title={<span className="inline-flex items-center gap-1">분기별 기록<InfoTip label="분기별 기록 설명">%p는 {chain.etf} 대비 초과수익이고, 목표가는 발표 후 7일 안의 변경 건수입니다.</InfoTip></span>}>
      <div className="overflow-x-auto">
        <Table className="text-sm">
          <TableHeader>
            <TableRow>
              <TableHead>분기</TableHead><TableHead>발표일</TableHead>
              <TableHead className="text-right">첫 거래일</TableHead><TableHead className="text-right">일주일</TableHead>
              <TableHead className="text-right">목표가 올림·내림</TableHead><TableHead>반응 한 줄</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {chain.history.map((r) => {
              const cur = r.transcript_id === transcriptId
              return (
                <TableRow key={`${r.fiscal}-${r.event_date}`} className={cn(cur && "bg-primary/5 hover:bg-primary/5")}>
                  <TableCell className="font-semibold whitespace-nowrap">{r.fiscal}</TableCell>
                  <TableCell className="tabular-nums whitespace-nowrap">{mmdd(r.event_date)}</TableCell>
                  <TableCell className="text-right"><Pp v={r.d1} /></TableCell>
                  <TableCell className="text-right"><Pp v={r.d7} /></TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {r.pt_up == null && r.pt_down == null ? <span className="text-muted-foreground">-</span>
                      : <><span className="text-up-ink">{r.pt_up ?? 0}</span> · <span className="text-down-ink">{r.pt_down ?? 0}</span></>}
                  </TableCell>
                  <TableCell className="min-w-56 whitespace-normal">
                    {r.headline ?? <span className="inline-flex flex-wrap items-center gap-1.5 text-muted-foreground">
                      정리 없음
                      {r.transcript_id && !cur && <Button variant="ghost" size="xs" onClick={() => onSelect(r.transcript_id!)}>이 분기 보기</Button>}
                    </span>}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </Section>
  )
}
