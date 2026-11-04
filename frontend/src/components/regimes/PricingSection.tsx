import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ChevronRight, ExternalLink } from "lucide-react"
import { BlockError } from "@/components/home/blockState"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toggle } from "@/components/ui/toggle"
import { usePricing } from "@/hooks/useRegimes"
import { cn } from "@/lib/utils"
import { formatBp, formatPercent } from "@/utils/format"
import type { PricingClaim, PricingPrice, PricingStance, PricingStatus } from "@/types"
import { InfoTip, Section } from "./Section"

const THEME: Record<string, string> = { rates: "금리", inflation: "물가", growth: "성장", credit: "신용", geopolitics: "지정학", energy: "에너지",
  ai: "AI", sector: "섹터", fx: "환율", policy: "정책", other: "기타" }
const STATUS: Record<PricingStatus, { label: string; cls: string }> = {
  new: { label: "새로 등장", cls: "border-primary/40 text-primary" },
  stronger: { label: "강해짐", cls: "border-up/40 text-up" },
  weaker: { label: "약해짐·반론", cls: "border-chart-warning/50 text-hypothesis" },
  faded: { label: "사라짐", cls: "text-muted-foreground" },
  ongoing: { label: "지속", cls: "text-muted-foreground" },
  dormant: { label: "지난 전제", cls: "text-muted-foreground" },
}
const DOT: Record<PricingStance, string> = {
  present: "bg-primary/60",
  stronger: "bg-up",
  weaker: "bg-chart-warning",
  contested: "bg-chart-warning ring-2 ring-chart-warning/30",
}

function chg(p: PricingPrice, v: number | null) {
  if (v == null) return "-"
  return p.mode === "bp" ? `${formatBp(v, true)}bp` : p.mode === "pct" ? formatPercent(v) : `${v > 0 ? "+" : ""}${v.toFixed(1)}`
}
const tone = (v: number | null) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up" : "text-down"

/**
 * 시장이 가격에 반영하는 것(docs/specs/pricing-ledger.md §7) — 매일 브리핑에서 이어 본 전제 타임라인 + 가격 층.
 * 지난 전제 보기는 URL `pricing_all`, 행 펼침은 화면 편의라 로컬 상태.
 * 아직 전제를 뽑지 않은 날(pending)은 아침 브리핑 작업이 잇는다 — 화면에는 띠의 빈 칸으로만 보인다(상태 시트 §4.28).
 */
export function PricingSection() {
  const q = usePricing(8)
  const [params, setParams] = useSearchParams()
  const showAll = params.get("pricing_all") === "1"
  const [open, setOpen] = useState<number | null>(null)
  const how = <>매일 아침 미국장 브리핑에서 '시장이 믿고 움직이는 기대'(전제)를 뽑아 날짜를 넘어 이어 붙였습니다. 한 줄이 한 전제이고, 점은 그 전제가 브리핑에 나온 날입니다. 위쪽의 <b>새로 등장·강해짐·약해짐·사라짐</b>이 이번 주 시장 이야기의 변화이고, 아래 가격 표는 같은 기간 시장 가격이 실제로 어떻게 움직였는지입니다. 이야기와 가격이 같은 쪽을 가리키면 이미 가격에 반영된 것, 엇갈리면 아직 반영되지 않았거나 이야기가 과장된 것일 수 있습니다. 전제는 AI가 브리핑을 읽고 뽑은 것이라 출처로 확인하세요.</>

  if (q.isPending) return <Section id="now-pricing" step={5} title="시장이 가격에 반영하는 것" how={how}><Skeleton className="h-64 w-full" /></Section>
  if (q.isError) return <Section id="now-pricing" step={5} title="시장이 가격에 반영하는 것" how={how}><BlockError message="프라이싱 원장을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /></Section>
  const d = q.data
  const claims = d.claims.filter(c => showAll || c.status !== "dormant")
  const priceByKey = Object.fromEntries(d.prices.map(p => [p.key, p]))

  return <Section id="now-pricing" step={5} title="시장이 가격에 반영하는 것" how={how}>
    {!d.claims.length ? <p className="py-8 text-center text-sm text-muted-foreground">{d.days.length ? "아직 뽑은 전제가 없습니다." : "저장된 미국장 브리핑이 없습니다."}</p> : <>
      <div className="grid gap-2 md:grid-cols-4">
        {(["new", "stronger", "weaker", "faded"] as const).map(k => <div key={k} className="rounded-lg border px-3 py-2">
          <div className="flex items-center justify-between"><Badge variant="outline" className={cn("font-normal", STATUS[k].cls)}>{STATUS[k].label}</Badge><span className="text-caption tabular-nums text-muted-foreground">{d.summary[k].length}</span></div>
          <ul className="mt-1.5 space-y-1 text-caption">{d.summary[k].slice(0, 3).map(s => <li key={s} className="line-clamp-2">{s}</li>)}
            {!d.summary[k].length && <li className="text-muted-foreground">없음</li>}</ul>
        </div>)}
      </div>
      <p className="flex items-center gap-1 text-caption text-muted-foreground">기준 {d.as_of} 브리핑
        <InfoTip label="집계 기준">이번 주 = 최근 5개 브리핑일 · 사라짐 = 그 전 4주 동안 3번 이상 나오다 이번 주 안 나옴</InfoTip></p>

      <Table>
        <TableHeader><TableRow><TableHead>가격 지표</TableHead><TableHead className="text-right">지금</TableHead><TableHead className="text-right">1주</TableHead><TableHead className="text-right">4주</TableHead></TableRow></TableHeader>
        <TableBody>{d.prices.map(p => <TableRow key={p.key}>
          <TableCell className="text-sm">{p.label}</TableCell>
          <TableCell className="text-right tabular-nums">{p.value == null ? "-" : `${p.value}${p.unit === "%" ? "%" : ""}`}</TableCell>
          <TableCell className={cn("text-right tabular-nums", tone(p.chg_1w))}>{chg(p, p.chg_1w)}</TableCell>
          <TableCell className={cn("text-right tabular-nums", tone(p.chg_4w))}>{chg(p, p.chg_4w)}</TableCell>
        </TableRow>)}</TableBody>
      </Table>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium">전제 타임라인 <span className="font-normal text-muted-foreground">— 최근 {d.days.length}개 브리핑일</span></p>
          <div className="flex items-center gap-3">
            <div className="flex gap-2.5 text-[11px] text-muted-foreground">
              {(["present", "stronger", "weaker", "contested"] as const).map(s => <span key={s} className="flex items-center gap-1"><span className={cn("size-2 rounded-full", DOT[s])} />{{ present: "유지", stronger: "강해짐", weaker: "약해짐", contested: "반론" }[s]}</span>)}
            </div>
            <Toggle size="sm" variant="outline" pressed={showAll} className="text-caption"
              onPressedChange={v => setParams(prev => { const n = new URLSearchParams(prev); if (v) n.set("pricing_all", "1"); else n.delete("pricing_all"); return n }, { replace: true })}>지난 전제도</Toggle>
          </div>
        </div>
        <div className="overflow-x-auto">
          <div className="min-w-[760px] divide-y rounded-lg border">
            {claims.map(c => <ClaimRow key={c.id} c={c} days={d.days} open={open === c.id} onToggle={() => setOpen(open === c.id ? null : c.id)} prices={priceByKey} />)}
          </div>
        </div>
      </div>
    </>}
  </Section>
}

function ClaimRow({ c, days, open, onToggle, prices }: { c: PricingClaim; days: string[]; open: boolean; onToggle: () => void; prices: Record<string, PricingPrice> }) {
  const seen = new Map(c.dates)
  return <div>
    <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/40">
      <ChevronRight className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
      <div className="w-[300px] shrink-0">
        <div className="line-clamp-2 text-[13px] leading-snug">{c.statement}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Badge variant="outline" className={cn("px-1.5 py-0 text-[10px] font-normal", STATUS[c.status].cls)}>{STATUS[c.status].label}</Badge>
          {THEME[c.theme] ?? c.theme} · {c.first_seen.slice(5)}~ · {c.days_seen}일
        </div>
      </div>
      <div className="flex flex-1 items-center gap-[3px]" aria-label={`관측 ${c.days_seen}일`}>
        {days.map(day => { const s = seen.get(day); return <span key={day} title={s ? `${day} ${s}` : day}
          className={cn("size-2 shrink-0 rounded-full", s ? DOT[s] : "bg-muted")} /> })}
      </div>
    </button>
    {open && c.latest && <div className="space-y-1.5 bg-muted/30 px-10 py-2.5 text-caption">
      <p><span className="text-muted-foreground">최근 근거({c.latest.date}) </span>{c.latest.evidence}</p>
      {c.latest.sources.length > 0 && <div className="flex flex-wrap gap-x-3 gap-y-1">
        {c.latest.sources.map((s, i) => s.doc_id ? <Link key={i} to={`/doc/${s.doc_id}`} className="text-primary hover:underline">{s.publisher} · {s.title}</Link>
          : s.url ? <a key={i} href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">{s.publisher} · {s.title}<ExternalLink className="size-3" aria-hidden="true" /></a>
          : <span key={i}>{s.publisher} · {s.title}</span>)}
      </div>}
      {c.related.length > 0 && <p className="text-muted-foreground">관련 가격(4주): {c.related.map(k => prices[k]).filter(Boolean).map(p => `${p.label} ${chg(p, p.chg_4w)}`).join(" · ")}</p>}
    </div>}
  </div>
}

/** 모바일 요약 — 이번 주 움직인 전제 4건과 전체 원장으로 가는 링크 (Mobile-Macro) */
export function PricingCompact() {
  const q = usePricing(8)
  if (q.isPending) return <Skeleton className="h-40 w-full" />
  if (q.isError) return <BlockError message="프라이싱 원장을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
  const top = q.data.claims.filter(c => c.status !== "dormant" && c.status !== "ongoing").slice(0, 4)
  return <div className="space-y-2">
    {!top.length ? <p className="text-sm text-muted-foreground">이번 주 새로 움직인 전제가 없습니다.</p>
      : <ul className="divide-y border-y">{top.map(c => <li key={c.id} className="flex items-start gap-2 py-2 text-[13px] leading-snug">
        <Badge variant="outline" className={cn("shrink-0 font-normal", STATUS[c.status].cls)}>{STATUS[c.status].label}</Badge>{c.statement}
      </li>)}</ul>}
    <Link to="/home/macro?macro_view=full#now-pricing" className="inline-block text-caption underline underline-offset-2">프라이싱 원장 전체 ›</Link>
  </div>
}
