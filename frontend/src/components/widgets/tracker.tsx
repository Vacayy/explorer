import { Fragment, useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Plus, X } from "lucide-react"
import CandlestickChart from "@/components/charts/CandlestickChart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { prepareTracker, useTracker, useTrackerConditionMutations } from "@/hooks/useTracker"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber, formatPercent, formatPp, formatRatio } from "@/utils/format"
import type { TrackerCondition, TrackerKind, TrackerRole, TrackerView } from "@/types"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/**
 * 종목 추적 위젯(docs/specs/stock-tracker.md) — 종목마다 하나. 내 원칙 조건 → 차트·기술적 신호 → 수급 → 이슈 순.
 * 조건 충족·급등락·공시·새 기술적 신호는 서버가 텔레그램으로도 알린다(portfolio_alerts 편승).
 */

const codeOf = (p?: Record<string, unknown>) => (typeof p?.code === "string" ? p.code : null)
const tone = (v?: number | null) => (v == null ? "text-muted-foreground" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted-foreground")
const won = (eok: number) => formatKrw(eok * 1e8)
const KIND_LABEL: Record<TrackerKind, string> = {
  price_below: "가격 아래(손절선)", price_above: "가격 위(돌파)", close_below_ma: "N일선 아래 마감", close_above_ma: "N일선 위 마감", manual: "확인 항목(직접 체크)",
}
const ROLE_LABEL: Record<TrackerRole, string> = { entry: "진입", exit: "손절·청산", check: "확인" }

function useTrackerMeta(params?: Record<string, unknown>): WidgetMeta {
  const q = useTracker(codeOf(params))
  const t = q.data?.as_of ?? ""       // 장중 = ISO 시각('2026-10-21T09:30:06+09:00'), 종가 = 'YYYY-MM-DD'
  const label = !q.data ? null : q.data.source === "live" ? `${t.slice(5, 10)} ${t.slice(11, 16)} 장중` : `${t.slice(5, 10) || "-"} 종가`
  return { asOf: label, stale: q.isError }
}

function StatusBadge({ c }: { c: TrackerCondition }) {
  if (c.status === "pending") return <Badge variant="outline" className="text-[10px]">확인 대기</Badge>
  if (c.status === "met") return <Badge className={cn("text-[10px]", c.role === "exit" ? "bg-down text-white" : "bg-up text-white")}>충족</Badge>
  if (c.status === "not_met") return <Badge variant="secondary" className="text-[10px]">미충족</Badge>
  return <Badge variant="outline" className="text-[10px]">판정 불가</Badge>
}

function Conditions({ data, compact }: { data: TrackerView; compact?: boolean }) {
  const { patch, remove } = useTrackerConditionMutations(data.code)
  const [open, setOpen] = useState(false)
  return <section>
    <div className="mb-1 flex items-center justify-between">
      <p className="text-caption font-medium text-muted-foreground">내 원칙 조건</p>
      {!compact && <Button variant="ghost" size="sm" className="h-6 px-1.5 text-caption" onClick={() => setOpen(true)}><Plus className="size-3" />조건</Button>}
    </div>
    {!data.conditions.length ? <p className="text-caption text-muted-foreground">조건이 없어요. 진입·손절 조건을 미리 적어 두면 충족될 때 알려 드려요.</p>
      : <ul className="space-y-1">{data.conditions.map(c => <li key={c.id} className="flex items-center gap-2 text-caption">
        {c.kind === "manual"
          ? <Checkbox checked={!!c.done} onCheckedChange={v => patch.mutate({ id: c.id, done: v ? 1 : 0 })} aria-label={`${c.label} 확인`} />
          : <StatusBadge c={c} />}
        <span className="min-w-0 flex-1 truncate" title={c.note ?? c.label}>
          <span className="text-muted-foreground">{ROLE_LABEL[c.role]} · </span>{c.label}
          {c.level ? <span className="tabular-nums text-muted-foreground"> {formatNumber(c.level)}원</span> : null}
          {c.ref ? <span className="tabular-nums text-muted-foreground"> ({c.ma}일선 {formatNumber(c.ref)}원)</span> : null}
        </span>
        {c.distance_pct != null && <span className={cn("shrink-0 tabular-nums", tone(c.distance_pct))}>{formatPercent(c.distance_pct)}</span>}
        {!compact && <Button variant="ghost" size="icon-xs" aria-label={`${c.label} 삭제`} onClick={() => remove.mutate(c.id)}><X className="size-3" /></Button>}
      </li>)}</ul>}
    <ConditionDialog code={data.code} open={open} onOpenChange={setOpen} price={data.price} />
  </section>
}

function ConditionDialog({ code, open, onOpenChange, price }: { code: string; open: boolean; onOpenChange: (v: boolean) => void; price: number | null }) {
  const { add } = useTrackerConditionMutations(code)
  const [role, setRole] = useState<TrackerRole>("exit")
  const [kind, setKind] = useState<TrackerKind>("price_below")
  const [num, setNum] = useState("")
  const [label, setLabel] = useState("")
  const isMa = kind.endsWith("_ma"), isPrice = kind.startsWith("price_")
  const auto = isPrice ? `${KIND_LABEL[kind].split("(")[0]}` : isMa ? `${num || "N"}일선 ${kind === "close_above_ma" ? "위" : "아래"} 마감` : ""
  const ok = (kind === "manual" ? !!label.trim() : !!Number(num))
  const submit = () => add.mutate({ role, kind, label: label.trim() || auto, level: isPrice ? Number(num) : null, ma: isMa ? Number(num) : null },
    { onSuccess: () => { onOpenChange(false); setNum(""); setLabel("") } })
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>원칙 조건 추가</DialogTitle>
        <DialogDescription>손절 라인은 진입 전에 정하고 사후에 옮기지 않아요. 충족되면 텔레그램으로 알려 드려요(가격 조건은 장중, 이평선 조건은 장 마감에 판정).</DialogDescription>
      </DialogHeader>
      <div className="grid gap-3">
        <div className="grid grid-cols-2 gap-2">
          <div className="grid gap-1"><Label>역할</Label>
            <Select value={role} onValueChange={v => setRole(v as TrackerRole)}><SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{(Object.keys(ROLE_LABEL) as TrackerRole[]).map(r => <SelectItem key={r} value={r}>{ROLE_LABEL[r]}</SelectItem>)}</SelectContent></Select></div>
          <div className="grid gap-1"><Label>종류</Label>
            <Select value={kind} onValueChange={v => setKind(v as TrackerKind)}><SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{(Object.keys(KIND_LABEL) as TrackerKind[]).map(k => <SelectItem key={k} value={k}>{KIND_LABEL[k]}</SelectItem>)}</SelectContent></Select></div>
        </div>
        {kind !== "manual" && <div className="grid gap-1">
          <Label>{isPrice ? `기준가(원)${price ? ` — 현재 ${formatNumber(price)}원` : ""}` : "이평선 N일"}</Label>
          <Input inputMode="numeric" value={num} onChange={e => setNum(e.target.value.replace(/[^0-9]/g, ""))} placeholder={isPrice ? "예: 10780" : "예: 120"} />
          {isPrice && price && Number(num) > 0 && <p className="text-caption text-muted-foreground">현재가 대비 {formatPercent((Number(num) / price - 1) * 100)}</p>}
        </div>}
        <div className="grid gap-1"><Label>{kind === "manual" ? "확인할 것" : "이름(선택)"}</Label>
          <Input value={label} onChange={e => setLabel(e.target.value)} placeholder={kind === "manual" ? "예: 3분기 반도체 부문 매출 증가 확인" : auto} /></div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
        <Button disabled={!ok || add.isPending} onClick={submit}>추가</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}

function Chart({ data }: { data: TrackerView }) {
  const s = data.chart.series
  const line = (k: "ma20" | "ma60" | "ma120") => s.filter(b => b[k] != null).map(b => ({ time: b.t, value: b[k] as number }))
  const levels = data.conditions.filter(c => c.kind.startsWith("price_") && c.level)
    .map(c => ({ id: `c${c.id}`, title: c.label, token: c.role === "exit" ? "--chart-negative" : "--chart-profit", dashed: true,
      data: s.map(b => ({ time: b.t, value: c.level as number })) }))
  return <CandlestickChart height={190} data={s.map(b => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }))}
    overlays={[{ id: "ma20", title: "20일", token: "--chart-1", data: line("ma20") }, { id: "ma60", title: "60일", token: "--chart-2", data: line("ma60") },
      { id: "ma120", title: "120일", token: "--chart-3", data: line("ma120") }, ...levels]} />
}

function Technicals({ t }: { t: TrackerView["technicals"] }) {
  const chip = (label: string, v: string, cls = "") => <span className="rounded bg-muted px-1.5 py-0.5"><span className="text-muted-foreground">{label} </span><span className={cn("tabular-nums", cls)}>{v}</span></span>
  return <section>
    <p className="mb-1 text-caption font-medium text-muted-foreground">기술적 신호</p>
    <div className="flex flex-wrap gap-1 text-caption">
      {chip("52주 고점", formatPercent(t.off_52w_high), tone(t.off_52w_high))}
      {chip("20·60·120선", `${formatPercent(t.ma20_gap)} · ${formatPercent(t.ma60_gap)} · ${formatPercent(t.ma120_gap)}`)}
      {t.volume_ratio != null && chip("거래량", `${t.volume_ratio}배`, t.volume_ratio >= 2 ? "text-up" : "")}
      {t.rs != null && chip("상대강도", `${t.rs}`)}
      {t.overhead_pct != null && chip("머리 위 매물", formatRatio(t.overhead_pct))}
      {t.regime?.posture && <span title={t.regime.reason ?? ""} className="rounded bg-muted px-1.5 py-0.5"><span className="text-muted-foreground">시장 국면 </span>{t.regime.posture}</span>}
    </div>
    {!!t.signals?.length && <ul className="mt-1 space-y-0.5 text-caption">{t.signals.slice(0, 4).map(s => <li key={`${s.id}${s.date}`}>
      <span className="tabular-nums text-muted-foreground">{s.date.slice(5)}</span> {s.label}</li>)}</ul>}
  </section>
}

function Flows({ data }: { data: TrackerView }) {
  const f = data.flows
  const prepared = useRef(false)
  useEffect(() => { if (!f && !prepared.current) { prepared.current = true; void prepareTracker(data.code) } }, [f, data.code])
  return <section>
    <p className="mb-1 text-caption font-medium text-muted-foreground">수급{f ? ` · ${f.as_of.slice(5)}까지` : ""}</p>
    {!f ? <p className="text-caption text-muted-foreground">수급을 받는 중이에요(최근 30일). 잠시 뒤 채워져요.</p>
      : <div className="grid grid-cols-[auto_1fr_1fr] gap-x-3 gap-y-0.5 text-caption tabular-nums">
        <span /><span className="text-right text-muted-foreground">5일</span><span className="text-right text-muted-foreground">20일</span>
        {([["외국인", f.foreign_5d, f.foreign_20d], ["기관", f.inst_5d, f.inst_20d], ["개인", f.indiv_5d, f.indiv_20d]] as const).map(([n, a, b]) => <Fragment key={n}>
          <span className="text-muted-foreground">{n}</span>
          <span className={cn("text-right", tone(a))}>{won(a)}</span><span className={cn("text-right", tone(b))}>{won(b)}</span></Fragment>)}
        {f.foreign_ratio != null && <span className="col-span-3 text-muted-foreground">외국인 보유율 {formatRatio(f.foreign_ratio)} ({formatPp(f.foreign_ratio_chg, 2)}, 20일)</span>}
      </div>}
  </section>
}

function Issues({ i }: { i: TrackerView["issues"] }) {
  return <section>
    <p className="mb-1 text-caption font-medium text-muted-foreground">이슈 · 피드 7일 {i.docs_7d}건</p>
    <ul className="space-y-0.5 text-caption">
      {i.disclosures.slice(0, 4).map(d => <li key={`${d.date}${d.title}`} className="truncate">
        <span className="tabular-nums text-muted-foreground">{d.date.slice(4, 6)}-{d.date.slice(6)}</span>{" "}
        {d.url ? <a href={d.url} target="_blank" rel="noreferrer" className={cn("hover:underline", d.key && "font-medium text-primary")}>{d.title}</a> : d.title}
      </li>)}
      {i.target_prices.slice(0, 2).map(t => <li key={t.doc_id} className="truncate">
        <span className="tabular-nums text-muted-foreground">{t.date.slice(5)}</span> 목표가 <span className="tabular-nums font-medium">{formatNumber(t.value)}원</span>{" "}
        <Link to={`/doc/${t.doc_id}`} className="text-muted-foreground hover:underline">{t.title}</Link></li>)}
      {i.docs.slice(0, 3).map(d => <li key={d.id} className="truncate">
        <span className="tabular-nums text-muted-foreground">{d.published_at.slice(5, 10)}</span> <Link to={`/doc/${d.id}`} className="hover:underline">{d.title}</Link></li>)}
      {!i.disclosures.length && !i.docs.length && <li className="text-muted-foreground">최근 공시·문서가 없어요.</li>}
    </ul>
  </section>
}

function TrackerBody({ w, h, params }: WidgetBodyProps) {
  const code = codeOf(params)
  const q = useTracker(code)
  if (!code) return <p className="p-3 text-sm text-muted-foreground">종목이 정해지지 않은 위젯이에요. 빼고 '위젯 추가 › 종목 추적'에서 종목을 골라 다시 놓아 주세요.</p>
  if (q.isLoading) return <div className="space-y-2 p-3"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-40 w-full" /></div>
  if (q.isError || !q.data) return <ErrorState message="추적 카드를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
  const d = q.data
  const head = <div className="flex flex-wrap items-baseline gap-x-2">
    <span className="text-xl font-semibold tabular-nums">{d.price != null ? `${formatNumber(d.price)}원` : "-"}</span>
    <span className={cn("tabular-nums", tone(d.change_pct))}>{formatPercent(d.change_pct)}</span>
    <Link to={`/analyze/${d.code}/summary`} className="ml-auto text-caption text-muted-foreground hover:underline">기업 화면</Link>
  </div>
  if (h <= 3) {
    const met = d.conditions.filter(c => c.status === "met")
    const sig = d.technicals.signals?.[0]
    return <div className="space-y-1 p-3">
      {head}
      <p className="truncate text-caption">{met.length ? met.map(c => `${ROLE_LABEL[c.role]} 충족: ${c.label}`).join(" · ")
        : d.conditions.length ? `조건 ${d.conditions.length}개 미충족` : "원칙 조건 없음"}</p>
      {sig && <p className="truncate text-caption text-muted-foreground">{sig.date.slice(5)} {sig.label}</p>}
    </div>
  }
  const wide = w >= 7
  return <div className="h-full space-y-3 overflow-y-auto p-3">
    {head}
    <Conditions data={d} />
    <div className={cn("grid gap-3", wide && "grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]")}>
      <div className="min-w-0 space-y-3"><Chart data={d} /><Technicals t={d.technicals} /></div>
      <div className="min-w-0 space-y-3"><Flows data={d} /><Issues i={d.issues} /></div>
    </div>
  </div>
}

export const TRACKER_WIDGETS: WidgetDef[] = [
  { id: "track.stock", title: "종목 추적", description: "종목 하나의 원칙 조건·차트·기술적 신호·수급·이슈 — 종목마다 하나씩, 조건 충족 시 텔레그램 알림",
    section: "home", group: "관심 종목 추적", size: { w: 6, h: 8, minW: 3, minH: 2 }, multi: true, pick: "stock",
    titleOf: p => (typeof p?.name === "string" ? `${p.name} 추적` : "종목 추적"),
    detailPathOf: p => (codeOf(p) ? `/analyze/${codeOf(p)}/summary` : "/"),
    useMeta: useTrackerMeta, Body: TrackerBody },
]
