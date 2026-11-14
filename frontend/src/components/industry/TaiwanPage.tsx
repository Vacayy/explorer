import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { PageLayout } from "@/components/shared/PageLayout"
import FilterChips from "@/components/shared/FilterChips"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { BoundedArea } from "@/components/shared/Bounded"
import { ErrorState } from "@/components/shared/ErrorState"
import { TwStateBadge } from "@/components/shared/TwLinkSignal"
import { Skeleton } from "@/components/ui/skeleton"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { SummaryStrip, SummaryStripSkeleton } from "@/components/industry/SummaryStrip"
import { MonitorSection, MonitorWall, WallPager, wallPageSize, type MonitorCardData } from "@/components/industry/MonitorWall"
import { TwCompanyDialog, twStale } from "@/components/industry/TaiwanCompany"
import { useTwLinks, useTwRevenue } from "@/hooks/useTwRevenue"
import { useIsMobile } from "@/hooks/use-mobile"
import { monthLabel, movingAverage, pageOf } from "@/lib/trade"
import { cn } from "@/lib/utils"
import { formatNumber, formatPercent, formatTwdEok } from "@/utils/format"
import type { TwLink, TwRevenueItem, TwRevenueResponse } from "@/types"

/**
 * 산업 › 대만 공급망 (/follow/taiwan, 시안 Industry-TW, ia-redesign §4.8 11-06 모니터링형 · D-325 · docs/specs/tw-revenue.md).
 * 요약 4칸 → 대만 월매출 모니터(92개사 카드 벽, 계층 칩 · 정렬 · 24개씩 쪽) → 대만 → 한국 연결(카드 벽 5열, 높이 고정·안쪽 스크롤).
 * 카드를 누르면 가운데 대화상자(URL tw), 거기서 상세 페이지 /follow/taiwan/:code. 한국 카드는 도시에로.
 * URL: tw_layer(옛 위젯 층 주소 그대로) · tw_sort(yoy 기본 · revenue) · page · tw(대화상자). 새 API 없음 — /tw/revenue(36개월 포함)·/tw/links.
 */
type TwSort = "yoy" | "revenue"
const SORTS: { value: TwSort; label: string }[] = [{ value: "revenue", label: "매출 순" }, { value: "yoy", label: "전년 대비 순" }]
const UP50 = 50

export default function TaiwanPage() {
  const [params, setParams] = useSearchParams()
  const rev = useTwRevenue()
  const links = useTwLinks()
  const setMany = (kv: Record<string, string | null>) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) n.set(k, v); else n.delete(k) }
    return n
  }, { replace: true, preventScrollReset: true })
  if (rev.isError && links.isError) return <PageLayout mode="document"><ErrorState message="대만 월매출을 불러오지 못했습니다." onRetry={() => { void rev.refetch(); void links.refetch() }} /></PageLayout>
  const code = params.get("tw")
  return <PageLayout mode="document">
    <div className="flex flex-col">
      {rev.data && links.data ? <TwSummary d={rev.data} links={links.data.items} />
        : rev.isError ? <BlockError message="대만 월매출 요약을 불러오지 못했습니다" error={rev.error} onRetry={() => void rev.refetch()} /> : <SummaryStripSkeleton />}
      <RevenueMonitor q={rev} layer={params.get("tw_layer") ?? "all"} sort={params.get("tw_sort") === "revenue" ? "revenue" : "yoy"} page={Number(params.get("page") ?? 1)}
        onChange={kv => setMany({ ...kv, page: null })} onPage={p => setMany({ page: p > 1 ? String(p) : null })}
        hrefOf={p => { const n = new URLSearchParams(params); if (p > 1) n.set("page", String(p)); else n.delete("page"); return `?${n}` }}
        onOpen={v => setMany({ tw: v })} />
      <LinkWall q={links} />
    </div>
    <TwCompanyDialog code={code} item={rev.data?.items.find(i => i.code === code)} layers={rev.data?.layers ?? []} asOf={rev.data?.as_of ?? null} onClose={() => setMany({ tw: null })} />
  </PageLayout>
}

const median = (xs: number[]) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null }

function TwSummary({ d, links }: { d: TwRevenueResponse; links: TwLink[] }) {
  const yoys = d.items.map(i => i.yoy_pct).filter((v): v is number => v != null)
  const med = median(yoys)
  const states = links.reduce<Record<string, number>>((m, l) => ({ ...m, [l.state ?? "-"]: (m[l.state ?? "-"] ?? 0) + 1 }), {})
  return <SummaryStrip label="taiwan" cells={[
    { label: "공시", value: `${d.reported} / ${d.total}`, sub: <span className={cn(twStale(d.as_of) && "text-warn")}>{monthLabel(d.as_of)} 월매출</span> },
    { label: "전년 대비 중앙값", value: formatPercent(med), sub: `${formatNumber(yoys.length)}개사` },
    { label: `전년 대비 +${UP50}% 이상`, value: formatNumber(yoys.filter(v => v >= UP50).length), sub: "분홍 막대" },
    { label: "한국 연결", value: formatNumber(links.length), sub: Object.entries(states).map(([k, v]) => `${k} ${v}`).join(" · ") || "-" },
  ]} />
}

const toCard = (i: TwRevenueItem, layer: string): MonitorCardData => {
  const vals = i.series.map(p => p.revenue)
  const ma = movingAverage(vals)
  return {
    key: i.code, name: i.name, group: layer, value: formatTwdEok(i.revenue), yoy: i.yoy_pct, surge: (i.yoy_pct ?? 0) >= UP50,
    badge: i.lagging && i.ym ? `${+i.ym.slice(5, 7)}월분` : undefined, bars: vals.slice(-24), ma: ma.slice(-24),
  }
}

function RevenueMonitor({ q, layer, sort, page, onChange, onPage, hrefOf, onOpen }: {
  q: ReturnType<typeof useTwRevenue>; layer: string; sort: TwSort; page: number
  onChange: (kv: Record<string, string | null>) => void; onPage: (p: number) => void; hrefOf: (p: number) => string; onOpen: (code: string) => void
}) {
  const mobile = useIsMobile()
  const d = q.data
  const labels = useMemo(() => Object.fromEntries((d?.layers ?? []).map(l => [l.key, l.label])), [d])
  const l = d?.layers.some(x => x.key === layer) ? layer : "all"
  const list = (d?.items ?? []).filter(i => l === "all" || i.layer === l)
    .sort((a, b) => sort === "revenue" ? (b.revenue ?? -1) - (a.revenue ?? -1) : (b.yoy_pct ?? -1e9) - (a.yoy_pct ?? -1e9))
  const pg = pageOf(list, page, wallPageSize(mobile))
  const last = d?.as_of ? `${+d.as_of.slice(5, 7)}월` : "최신 달"
  return <MonitorSection label="tw.monitor">
    <BlockHead section title="대만 월매출 모니터" sub={<span className="max-sm:hidden">{`24개월 · 억 TWD · 막대 끝 = ${last} · 선 = 12개월 평균`}</span>}
      info="대만 상장사 월매출(공시)입니다. 분홍 막대는 전년 대비 +50% 이상. 카드를 누르면 상세가 가운데 창으로 열립니다." />
    <div className="flex items-center gap-2.5 max-lg:flex-col max-lg:items-stretch">
      {d ? <FilterChips options={[{ value: "all", label: `전체 ${d.items.length}` }, ...d.layers.map(x => ({ value: x.key, label: x.label }))]} value={l}
        onChange={v => onChange({ tw_layer: v === "all" ? null : v })} className="min-w-0 flex-1 flex-nowrap overflow-x-auto [scrollbar-width:none]" /> : <span className="h-7 flex-1" />}
      <SegmentTabs tabs={SORTS} value={sort} onChange={v => onChange({ tw_sort: v === "yoy" ? null : v })} />
    </div>
    {q.isError && !d ? <BlockError message="대만 월매출을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : d && !d.as_of ? <p role="status" className="text-sm text-ink-2">대만 월매출을 아직 받지 못했습니다. 매일 11:00에 수집합니다.</p>
      : <MonitorWall cards={pg.rows.map(i => toCard(i, labels[i.layer] ?? i.layer))} loading={q.isPending} onOpen={onOpen} empty="이 계층에는 회사가 없습니다." />}
    <WallPager from={pg.from} to={pg.to} total={list.length} page={pg.page} pages={pg.pages} hrefOf={hrefOf} onPage={onPage} />
  </MonitorSection>
}

/* ── 대만 → 한국 연결 — 한국 종목 카드 벽(5열), 높이 고정·안쪽 스크롤. 카드는 도시에로 ── */
const STATE_ORDER: Record<string, number> = { "전환↓": 0, "전환↑": 1, "둔화": 2, "가속": 3, "유지": 4 }
const SPARK: Record<string, string> = { "가속": "var(--up)", "전환↑": "var(--up)", "둔화": "var(--down)", "전환↓": "var(--down)" }
const LINK_H = "h-[300px]"

function YoySpark({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return <span className="block h-10" />
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1
  const pts = values.map((v, i) => `${(i / (values.length - 1) * 100).toFixed(1)},${(38 - (v - min) / span * 36).toFixed(1)}`).join(" ")
  return <svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden className="mt-auto block h-10 w-full">
    <polyline points={pts} fill="none" stroke={color} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
  </svg>
}

function LinkCard({ l }: { l: TwLink }) {
  return <Link to={`/analyze/${l.kr_code}/summary`} data-tw-link className="-mr-px -mb-px flex h-[150px] min-w-0 flex-col gap-[5px] border bg-card p-3 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-ring">
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="min-w-0 truncate text-[13.5px] font-semibold">{l.kr_name}</span>
      <TwStateBadge link={l} />
      <span className="ml-auto shrink-0 text-[11px] text-ink-3 max-sm:hidden">근거 {l.confidence}</span>
    </span>
    <span className="truncate text-[11.5px] text-ink-3">← {l.tw.map(t => t.name).join("·")}</span>
    <span className="truncate text-xs text-ink-3"><span className="max-sm:hidden">3개월 전년 대비 </span><span className="font-mono tabular-nums">{formatPercent(l.yoy_3m_prev)} →</span>{" "}
      <span className={cn("font-mono text-[12.5px] tabular-nums", tone(l.yoy_3m))}>{formatPercent(l.yoy_3m)}</span></span>
    <YoySpark values={l.series.slice(-24).map(s => s.yoy)} color={SPARK[l.state ?? ""] ?? "var(--ink-2)"} />
  </Link>
}

function LinkWall({ q }: { q: ReturnType<typeof useTwLinks> }) {
  const d = q.data
  const rows = useMemo(() => [...(d?.items ?? [])].sort((a, b) => (STATE_ORDER[a.state ?? "유지"] ?? 9) - (STATE_ORDER[b.state ?? "유지"] ?? 9)), [d])
  const acc = rows.filter(r => r.state === "가속").length
  return <MonitorSection label="tw.links">
    <BlockHead section title="대만 → 한국 연결" sub={d ? `연결 ${rows.length} · 가속 ${acc}` : undefined}
      info="대만 업체 월매출의 3개월 전년 대비가 빨라지면 같은 업황의 한국 종목에 '가속'을 붙입니다. 근거 상·중·하는 사업 근거와 동행 상관입니다." />
    {!d ? (q.isError ? <BlockError message="대만 → 한국 연결을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : <div role="status" aria-label="불러오는 중" className={cn(LINK_H, "grid grid-cols-2 content-start gap-px md:grid-cols-5")}>{Array.from({ length: 10 }, (_, i) => <Skeleton key={i} className="h-[149px] rounded-none" />)}</div>)
      : !rows.length ? <p role="status" className="text-sm text-ink-2">대만 연결이 아직 없습니다.</p>
      : <BoundedArea viewportClassName={cn(LINK_H, "!max-h-none")} aria-label="대만 → 한국 연결">
        <div className="grid grid-cols-2 pr-px pb-px md:grid-cols-5">{rows.map(l => <LinkCard key={`${l.kr_code}-${l.relation}-${l.tw[0]?.code}`} l={l} />)}</div>
      </BoundedArea>}
  </MonitorSection>
}
