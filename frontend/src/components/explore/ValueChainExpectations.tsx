import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { MetricHint } from "@/components/shared/MetricHint"
import { cn } from "@/lib/utils"
import { formatPercent, formatPp } from "@/utils/format"
import type { ExpClaim, ExpGapRow, ExpNode, ExpectationsResponse } from "@/types"

/**
 * 시장 기대치(docs/specs/value-chain.md §15) — 사실(관측)과 섞지 않고 따로 보인다.
 * 칸 기대 = 구성 회사 애널리스트 매출 컨센서스 합의 성장률, 개정 = EPS 추정의 30·90일 변화, 차이 = 관측 − 기대(이번 분기).
 */

const pct = (g?: number | null) => g == null ? "-" : formatPercent(g * 100)   // 소수 성장률 → %
const tone = (v?: number | null) => v == null ? "text-muted-foreground" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted-foreground"
const GAP_HINT = "관측은 최근 3개월(미국 칸은 최신 분기) 전년 대비, 기대는 구성 회사 애널리스트가 본 이번 분기 매출의 전년 대비 성장률입니다. 회사마다 회계 분기가 달라 근사 비교이고, 회사 전체 컨센서스라 칸 밖 사업이 섞일 수 있습니다."

const KIND: Record<string, string> = { price: "가격", shipments: "출하", revenue: "매출", market: "시장", growth: "성장", capex: "설비투자",
  production: "생산", supply: "공급", demand: "수요", cost: "원가" }
const BASIS: Record<string, string> = { yoy: "전년 대비", qoq: "전분기 대비", hoh: "전반기 대비", cum: "누적" }
/** 'shipments_yoy' → '출하 전년 대비' — 같은 대상의 출하·매출 전망을 구분한다 */
const metricLabel = (m: string) => { const [k, b] = m.split("_"); return `${KIND[k] ?? k} ${BASIS[b] ?? b ?? ""}`.trim() }

function claimText(c: ExpClaim) {
  const v = c.value_low == null ? "" : c.value_high != null && c.value_high !== c.value_low ? `${c.value_low}~${c.value_high}${c.unit ?? ""}` : `${c.value_low}${c.unit ?? ""}`
  return `${c.subject || "-"} · ${metricLabel(c.metric)} ${c.target_period ?? ""} ${v}`.replace(/\s+/g, " ").trim()
}

/** 칸 상세 아래 — 칸 합계 기대·개정·관측과의 차이, 구성 회사, 리서치 전망 */
export function ExpectationPanel({ exp, asOf }: { exp?: ExpNode; asOf?: string | null }) {
  if (!exp) return <div className="rounded-lg border border-dashed p-3 text-caption text-muted-foreground">이 칸은 시장 기대(컨센서스·리서치 전망) 자료가 없습니다 — 설비투자·회사채·수주잔고 칸은 매출 컨센서스가 칸의 기대가 아니어서 비워 둡니다.</div>
  return <div className="space-y-3 rounded-lg border border-dashed p-3 text-sm">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="font-semibold">시장 기대</span>
      <span className="text-caption text-muted-foreground">사실과 분리 · 애널리스트 컨센서스(yfinance) {asOf ?? "-"} · 구성 회사 {exp.coverage}</span>
    </div>
    <div className="grid gap-2 text-caption tabular-nums sm:grid-cols-2 lg:grid-cols-4">
      <div><p className="text-muted-foreground">이번 분기 기대</p><p className={cn("text-base font-semibold", tone(exp.exp_0q))}>{formatPercent(exp.exp_0q)}</p></div>
      <div><p className="text-muted-foreground">올해 · 내년</p><p className="text-base font-semibold">{formatPercent(exp.exp_0y)} · {formatPercent(exp.exp_1y)}</p></div>
      <div><p className="text-muted-foreground">EPS 추정 개정(30일 · 90일)</p><p className={cn("text-base font-semibold", tone(exp.eps_rev_30d))}>{formatPercent(exp.eps_rev_30d)} · <span className={tone(exp.eps_rev_90d)}>{formatPercent(exp.eps_rev_90d)}</span></p></div>
      <div><p className="text-muted-foreground"><MetricHint hint={GAP_HINT}><span className="underline decoration-dotted underline-offset-2">관측 − 기대(이번 분기)</span></MetricHint></p>
        <p className={cn("text-base font-semibold", tone(exp.gap_pp))}>{exp.gap_pp == null ? "-" : formatPp(exp.gap_pp, 1)}</p>
        <p className="text-muted-foreground">관측 {formatPercent(exp.observed)}{exp.obs_kind === "proxy" ? " · 대리 관측(업계 수출)이라 비교는 참고만" : ""}</p></div>
    </div>
    {exp.note && <p className="text-caption text-muted-foreground">{exp.note}</p>}
    {exp.members.length > 0 && <Table className="text-caption tabular-nums">
      <TableHeader><TableRow>
        <TableHead className="h-7">회사</TableHead>{["이번 분기", "다음 분기", "올해", "내년", "EPS 개정 30일", "애널리스트"].map(h => <TableHead key={h} className="h-7 text-right">{h}</TableHead>)}
      </TableRow></TableHeader>
      <TableBody>{exp.members.map(m => {
        const y = m.periods["0y"]; const rev = y?.eps_avg != null && y?.eps_30d ? (y.eps_avg / y.eps_30d - 1) * 100 * (y.eps_30d > 0 ? 1 : -1) : null
        return <TableRow key={m.symbol}>
          <TableCell className="py-1">{m.name} <span className="text-muted-foreground">{m.symbol}</span></TableCell>
          <TableCell className="py-1 text-right">{pct(m.periods["0q"]?.rev_growth)}</TableCell><TableCell className="py-1 text-right">{pct(m.periods["+1q"]?.rev_growth)}</TableCell>
          <TableCell className="py-1 text-right">{pct(y?.rev_growth)}</TableCell><TableCell className="py-1 text-right">{pct(m.periods["+1y"]?.rev_growth)}</TableCell>
          <TableCell className={cn("py-1 text-right", tone(rev))}>{formatPercent(rev)}</TableCell><TableCell className="py-1 text-right">{y?.analysts ?? "-"}</TableCell>
        </TableRow>
      })}</TableBody>
    </Table>}
    {exp.claims.length > 0 && <div>
      <p className="text-caption font-medium text-muted-foreground">리서치·증권사 전망</p>
      <ul className="divide-y text-caption">{exp.claims.map((c, i) => <li key={i} className="flex flex-wrap items-baseline gap-x-2 py-1">
        <Badge variant={c.source === "feed" ? "secondary" : "outline"} className="text-[10px]" title={c.source === "feed" ? "피드 문서에서 추출한 증권사·기관 전망(원문 인용 확인)" : "리서치 기관 공개 전망"}>
          {c.source_org ?? c.source}{c.source === "feed" ? " · 피드" : ""}</Badge>
        <MetricHint hint={c.quote ?? ""}><span className={cn("underline decoration-dotted underline-offset-2", c.direction === "up" ? "text-up" : c.direction === "down" ? "text-down" : "")}>{claimText(c)}</span></MetricHint>
        <span className="text-muted-foreground">{c.published_at?.slice(0, 10)}</span>
        {c.url && <a href={c.url} target="_blank" rel="noreferrer" className="text-muted-foreground underline underline-offset-2">원문</a>}
      </li>)}</ul>
    </div>}
  </div>
}

/** 사실 vs 기대 — 관측이 기대보다 크게 앞선 칸 / 기대가 관측보다 높은 칸 */
export function ExpGapCard({ data, onSelect }: { data: ExpectationsResponse; onSelect: (k: string) => void }) {
  const Row = ({ r }: { r: ExpGapRow }) => <Button variant="ghost" onClick={() => onSelect(r.key)} className="block h-auto w-full whitespace-normal rounded-md px-2 py-1.5 text-left text-sm font-normal">
    <span className="font-medium">{r.name}</span> <span className={cn("tabular-nums", tone(r.gap_pp))}>{formatPp(r.gap_pp, 1)}</span>
    <span className="block text-caption tabular-nums text-muted-foreground">관측 {formatPercent(r.observed)} · 기대 {formatPercent(r.exp_0q)} · EPS 추정 개정 30일 {formatPercent(r.eps_rev_30d)} · 90일 {formatPercent(r.eps_rev_90d)}</span>
  </Button>
  return <Card>
    <CardHeader className="pb-2">
      <CardTitle className="text-card-title">사실 vs 기대</CardTitle>
      <p className="text-caption text-muted-foreground">
        가격을 정하는 건 기대입니다. 칸 관측(사실)과 구성 회사 애널리스트 컨센서스(기대, 이번 분기 매출 성장률)의 차이가 ±{data.gap_pp}%p 이상인 칸 · {data.as_of ?? "-"} 기준.
        대리 관측 칸(한국 업계 수출)은 판정에서 뺍니다. <MetricHint hint={GAP_HINT}><span className="underline decoration-dotted underline-offset-2">비교 방식</span></MetricHint>
      </p>
    </CardHeader>
    <CardContent className="grid gap-5 lg:grid-cols-2">
      <div><p className="text-caption font-medium text-muted-foreground">관측이 기대보다 앞선 칸 — 추정이 따라 올라갈 여지</p>
        {data.ahead.length ? data.ahead.map(r => <Row key={r.key} r={r} />) : <p className="px-2 text-caption text-muted-foreground">해당 칸이 없습니다.</p>}</div>
      <div><p className="text-caption font-medium text-muted-foreground">기대가 관측보다 높은 칸 — 실망 위험</p>
        {data.behind.length ? data.behind.map(r => <Row key={r.key} r={r} />) : <p className="px-2 text-caption text-muted-foreground">해당 칸이 없습니다.</p>}</div>
    </CardContent>
  </Card>
}
