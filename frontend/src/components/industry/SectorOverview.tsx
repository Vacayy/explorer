import { Link } from "react-router-dom"
import { SectorIndexChart, rangeReturns } from "@/components/charts/SectorIndexChart"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { AiLine, Band, FillNote, FillSkeleton, MarketCard, Seg } from "@/components/home/MarketFrame"
import { FillArea } from "@/components/shared/Bounded"
import { AiBlock } from "@/components/shared/AiBlock"
import { Chip, RS_INFO, benchmarkName, benchmarkTip } from "@/components/industry/sectorParts"
import { useUrlParam } from "@/hooks/useUrlParam"
import SectorPeersTab from "@/components/industry/SectorPeersTab"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { formatPercent, formatUsd } from "@/utils/format"
import type { SectorDataLinkCard, IndustrySectorDetail, SectorDoc } from "@/types"
import type { useSectorDetail } from "@/hooks/useSectorView"

type Q = ReturnType<typeof useSectorDetail>
const mmdd = (d: string | null | undefined) => d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : "-"
const RANGES = [{ key: "1m", label: "1개월" }, { key: "3m", label: "3개월" }, { key: "1y", label: "1년" }, { key: "3y", label: "3년" }] as const
const RANGE_SUB: Record<string, string> = { "1m": "1개월 전 = 100", "3m": "3개월 전 = 100", "1y": "1년 전 = 100", "3y": "3년 전 = 100" }
export const DOC_KIND: Record<SectorDoc["type"], string> = { blog: "블로그", youtube: "유튜브", scrap: "스크랩", web: "웹" }
const DOC_FILTERS = [{ key: "all", label: "전체" }, { key: "research", label: "리서치" }, { key: "blog", label: "블로그" }, { key: "youtube", label: "유튜브" }] as const

/** 기간 자르기 — 1개월 21 · 3개월 63거래일, 1년·3년은 마지막 날에서 달력 기준 */
function slice(series: IndustrySectorDetail["series"], range: string) {
  if (range === "1m") return series.slice(-22)
  if (range === "3m") return series.slice(-64)
  if (!series.length) return series
  const last = new Date(`${series[series.length - 1].d}T00:00:00Z`)
  last.setUTCFullYear(last.getUTCFullYear() - (range === "3y" ? 3 : 1))
  const from = last.toISOString().slice(0, 10)
  return series.filter(p => p.d >= from)
}

/**
 * 섹터 화면 › 개요 (ia-redesign §4.35, 시안 Sector-Overview). 띠 셋, 칸마다 높이 고정(400 · 560 · 380)·넘침은 칸 안 스크롤.
 * ① 대표지수 vs 코스피(1개월·3개월·1년·3년, URL range) | 상대강도 4주 + 섹터 시총 비중 상위
 * ② 산업 개괄(AI, 내러티브 기반) + 이 산업의 내러티브 | 주요 자료(전체·리서치·블로그·유튜브, URL doc)
 * ③ Peer 그룹 — Peer 그룹 탭과 같은 컴포넌트(하위 그룹 목록 | 그룹 본문, 720 고정, 고른 그룹 URL ?group= 공유)
 * ④ 이 산업의 데이터 — 전체 폭 연결 카드 줄
 */
export default function SectorOverview({ q }: { q: Q }) {
  return <div className="flex flex-col gap-4">
    <Band label="대표지수와 상대강도" cells={[[8, <IndexCard key="i" q={q} />], [4, <RsCard key="r" q={q} />]]} />
    <Band label="산업 개괄과 주요 자료" cells={[[7, <OverviewCard key="o" q={q} />], [5, <DocsCard key="d" q={q} />]]} />
    {q.data?.name ? <SectorPeersTab sector={q.data.name} band="sectorPeerBlock" /> : <Band label="Peer 그룹" cells={[[12, <MarketCard key="p" band="sectorPeerBlock"><FillSkeleton rows={14} /></MarketCard>]]} />}
    <DataCard q={q} />
  </div>
}

function State({ q, rows, message, children }: { q: Q; rows?: number; message: string; children: (d: IndustrySectorDetail) => React.ReactNode }) {
  if (q.data) return <>{children(q.data)}</>
  return q.isError ? <BlockError message={message} error={q.error} onRetry={() => void q.refetch()} /> : <FillSkeleton rows={rows} />
}

function IndexCard({ q }: { q: Q }) {
  const [range, setRange] = useUrlParam("range", "1y")
  const d = q.data
  const b = d?.benchmark
  const pts = d ? slice(d.series, range) : []
  const r = rangeReturns(pts)
  return <MarketCard band="sectorChart" label="sector.index">
    <BlockHead section title={b ? `대표지수 · ${benchmarkName(b)}` : "대표지수"} info={b ? benchmarkTip(b) : undefined}
      sub={b ? `${b.kind === "etf" ? `${b.ticker} · ` : "시총 가중 · "}${RANGE_SUB[range] ?? ""}` : " "} />
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
      <div className="flex gap-3.5 text-xs text-ink-2">
        <span><span aria-hidden className="mr-1.5 inline-block h-0.5 w-3.5 bg-up align-middle" />{b ? benchmarkName(b) : "대표지수"} <span className={cn("font-mono", tone(r.v))}>{formatPercent(r.v)}</span></span>
        <span><span aria-hidden className="mr-1.5 inline-block w-3.5 border-t border-dashed border-ink-3 align-middle" />코스피 <span className={cn("font-mono", tone(r.k))}>{formatPercent(r.k)}</span></span>
      </div>
      <Seg label="기간" value={range} items={RANGES.map(x => ({ key: x.key, label: x.label }))} onChange={setRange} />
    </div>
    <State q={q} rows={8} message="대표지수를 불러오지 못했습니다">{() => pts.length < 2
      ? <FillNote>대표지수 시세가 쌓이면 나타납니다.</FillNote>
      : <SectorIndexChart points={pts} label={`대표지수와 코스피, ${RANGE_SUB[range]}`} className="min-h-0 flex-1" />}</State>
  </MarketCard>
}

function Bar({ v, cls }: { v: number | null; cls: string }) {
  return <div className="flex items-center gap-1.5">
    <div className="h-1.5 flex-1 rounded-[3px] bg-chip"><div className={cn("h-1.5 rounded-[3px]", cls)} style={{ width: `${Math.max(2, v ?? 0)}%` }} /></div>
    <span className="w-[26px] text-right font-mono tabular-nums">{v == null ? "-" : Math.round(v)}</span>
  </div>
}

function RsCard({ q }: { q: Q }) {
  return <MarketCard band="sectorChart" label="sector.rs">
    <BlockHead section title="상대강도" info={RS_INFO} sub="18개 섹터 중 백분위" />
    <State q={q} rows={8} message="상대강도를 불러오지 못했습니다">{d => {
      const rows = [...[...d.trail].sort((a, b) => b.weeks_ago - a.weeks_ago).map(t => ({ label: `${t.weeks_ago}주 전`, l: t.rs_long, s: t.rs_short })), { label: "지금", l: d.rs_long, s: d.rs_short }]
      return <>
        <div className="grid shrink-0 grid-cols-[56px_1fr_1fr] gap-2.5 text-[11.5px] text-ink-3"><span /><span>장기</span><span>단기</span></div>
        <div className="shrink-0">{rows.map(r => <div key={r.label} className="grid grid-cols-[56px_1fr_1fr] items-center gap-2.5 border-b py-1.5 text-[12.5px]">
          <span className="text-ink-3">{r.label}</span><Bar v={r.l} cls="bg-ink-2" /><Bar v={r.s} cls="bg-down" />
        </div>)}</div>
        <div className="mt-1 flex shrink-0 justify-between text-xs text-ink-3"><span>섹터 시총 비중 상위</span><span>비중 · 1개월</span></div>
        <FillArea aria-label="섹터 시총 비중 상위">{d.top_weights.map(c => <Link key={c.stock_code} to={`/analyze/${c.stock_code}/summary`}
          className="grid grid-cols-[minmax(0,1fr)_52px_62px] gap-2 border-b py-1.5 text-[12.5px] hover:bg-surface-2">
          <span className="truncate">{c.corp_name}</span>
          <span className="text-right font-mono text-ink-3 tabular-nums">{formatPercent(c.weight, 0).replace("+", "")}</span>
          <span className={cn("text-right font-mono tabular-nums", tone(c.ret_1m))}>{formatPercent(c.ret_1m)}</span>
        </Link>)}</FillArea>
      </>
    }}</State>
  </MarketCard>
}

function OverviewCard({ q }: { q: Q }) {
  const d = q.data
  const ov = d?.overview
  const n = d?.narratives.length ?? 0
  return <MarketCard band="sectorText" label="sector.overview">
    <BlockHead section title="산업 개괄" info="이 섹터에 걸린 내러티브와 최근 수집 자료로 AI가 정리합니다. 내러티브가 바뀔 때만 다시 쓰고, 섹터마다 주 1회가 상한입니다."
      sub={d ? `내러티브 ${n}개 · 자료 10일` : " "}
      link={d && n ? { to: `/narrative?topic=${encodeURIComponent(d.narratives[0].topic)}`, label: "Thesis에서 보기" } : null} />
    <State q={q} rows={10} message="산업 개괄을 불러오지 못했습니다">{d => <>
      {ov ? <>
        <AiLine>AI 요약 · 내러티브 기반 · {mmdd(ov.generated_at.slice(0, 10))} 갱신</AiLine>
        <AiBlock label="지금 이 산업의 질문" meta={ov.model ?? undefined} className="shrink-0">
          <p className="text-base leading-normal font-semibold">{ov.question}</p>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-[18px] text-[13px] leading-[1.7] text-ink-2">{ov.bullets.map(t => <li key={t}>{t}</li>)}</ul>
        </AiBlock>
      </> : <p role="status" className="shrink-0 bg-surface-2 px-4 py-3 text-[13px] text-ink-2">{n ? "개괄은 내러티브가 바뀌면 만들어집니다." : "연결된 내러티브 없음"}</p>}
      {n > 0 && <span className="shrink-0 text-xs text-ink-3">이 산업의 내러티브</span>}
      {n > 0 && <FillArea aria-label="이 산업의 내러티브">{d.narratives.map(x => <Link key={x.id} to={`/narrative?topic=${encodeURIComponent(x.topic)}`}
        className="flex flex-col gap-[3px] border-b py-[9px] hover:bg-surface-2">
        <span className="flex items-center gap-1.5"><Chip kind="hyp">{x.topic}</Chip><span className="ml-auto font-mono text-[11px] text-ink-3">자료 {x.docs ?? "-"}</span></span>
        <span className="text-[13px] leading-[1.55]">{x.title}</span>
      </Link>)}</FillArea>}
    </>}</State>
  </MarketCard>
}

function DocsCard({ q }: { q: Q }) {
  const [f, setF] = useUrlParam("doc", "all")
  const d = q.data
  const docs = (d?.docs ?? []).filter(x => f === "all" || (f === "research" ? x.type === "scrap" || x.type === "web" : x.type === f))
  const feed = d ? `/feed?view=documents&days=10&sort=latest${d.feed_industry ? `&industry=${encodeURIComponent(d.feed_industry)}` : ""}` : null
  return <MarketCard band="sectorText" label="sector.docs">
    <BlockHead section title="주요 자료" info="피드에 들어온 자료 중 이 섹터 업종·주제 태그나 시총 상위 종목이 붙은 것입니다. 리서치는 스크랩·웹 자료입니다." sub="최근 10일 · 리서치·블로그·유튜브"
      link={feed ? { to: feed, label: "피드에서 더 보기" } : null} />
    <Seg label="자료 종류" value={f} items={DOC_FILTERS.map(x => ({ key: x.key, label: x.label }))} onChange={setF} className="shrink-0 self-start" />
    <State q={q} rows={10} message="주요 자료를 불러오지 못했습니다">{() => !docs.length
      ? <FillNote>최근 10일 이 섹터 자료가 없습니다.</FillNote>
      : <FillArea aria-label="주요 자료">{docs.map(x => <Link key={x.id} to={`/doc/${x.id}`}
        className="grid grid-cols-[52px_minmax(0,1fr)_40px] items-baseline gap-2 border-b py-[9px] hover:bg-surface-2">
        <Chip className="justify-center text-[11px] font-normal">{DOC_KIND[x.type]}</Chip>
        <span className="line-clamp-2 text-[13px] leading-normal">{x.title}</span>
        <span className="text-right font-mono text-[11px] text-ink-3">{mmdd(x.published_at?.slice(0, 10))}</span>
      </Link>)}</FillArea>}</State>
  </MarketCard>
}

export function dataValue(c: SectorDataLinkCard): string | null {
  if (c.value == null) return c.verdict
  return c.value_kind === "usd" ? formatUsd(c.value) : formatPercent(c.value)
}

/** 연결 카드 하나 — 종류 › · 제목 · 값(Geist) + 변화 · 한 줄 */
export function DataLinkCard({ c, big }: { c: SectorDataLinkCard; big?: boolean }) {
  const v = dataValue(c)
  return <Link to={c.href} className={cn("flex min-h-[118px] min-w-0 flex-col gap-[3px] border bg-card p-3 hover:bg-surface-2", big && "min-h-[150px] gap-1.5 p-4")}>
    <span className="text-[11.5px] text-ink-3">{c.label} ›</span>
    <span className="truncate text-[13px] font-semibold">{c.title}</span>
    {v && <span className={cn("font-display tabular-nums", big ? "text-2xl" : "text-xl")}>{v}{c.change != null && <span className={cn("ml-1.5 font-mono text-[12.5px]", tone(c.change))}>{formatPercent(c.change)}</span>}</span>}
    <span className="line-clamp-2 text-[11.5px] text-ink-2">{c.sub}</span>
  </Link>
}

function DataCard({ q }: { q: Q }) {
  const d = q.data
  const cards = d?.data_links ?? []
  return <section aria-label="이 산업의 데이터" className="flex flex-col gap-3 rounded-[var(--radius-card)] border bg-card px-[18px] py-4">
    <BlockHead section title="이 산업의 데이터" info="이 섹터와 연결된 산업 데이터 화면입니다. 누르면 그 화면을 이 섹터 쪽으로 열어 줍니다."
      sub={d ? `연결 ${cards.length}` : "\u00a0"} link={cards.length ? { to: "?tab=data", label: "데이터 탭" } : null} />
    {q.isError ? <BlockError message="연결 데이터를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !d ? <div className="grid grid-cols-2 pr-px pb-px lg:grid-cols-5 [&>*]:-mr-px [&>*]:-mb-px">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-[118px] rounded-none border" />)}</div>
      : !cards.length ? <p role="status" className="text-sm text-ink-3">연결된 데이터 화면이 없습니다.</p>
      : <div className="grid grid-cols-1 pr-px pb-px sm:grid-cols-2 lg:grid-cols-5 [&>*]:-mr-px [&>*]:-mb-px">{cards.map(c => <DataLinkCard key={c.kind} c={c} />)}</div>}
  </section>
}
