import { Link, useParams } from "react-router-dom"
import { SectorIndexChart, rangeReturns } from "@/components/charts/SectorIndexChart"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { Band, FillNote, FillSkeleton, MarketCard, Seg } from "@/components/home/MarketFrame"
import { DataLinkCard, slice } from "@/components/industry/SectorOverview"
import { Chip, US_RS_INFO, usSectorPath } from "@/components/industry/sectorParts"
import { FillArea } from "@/components/shared/Bounded"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { PageLayout } from "@/components/shared/PageLayout"
import { PagerBar, paged } from "@/components/shared/PagerBar"
import { SparkLine } from "@/components/shared/Spark"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useUsSectorDetail } from "@/hooks/useSectorView"
import { useUrlParam } from "@/hooks/useUrlParam"
import { toApiError } from "@/api/query"
import { cn } from "@/lib/utils"
import { formatNumber, formatPercent, formatStockPrice, formatUsd } from "@/utils/format"
import type { UsSectorMarket, UsSectorDocType } from "@/types"

type Q = ReturnType<typeof useUsSectorDetail>
type MarketQuery<T extends UsSectorMarket = UsSectorMarket> = {
  data: T | undefined; isError: boolean; error: Error | null; refetch: () => unknown
}
const TABS = ["overview", "stocks", "data"] as const
type Tab = (typeof TABS)[number]
const mmdd = (d: string | null | undefined) => d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : "-"
const rsText = (v: number | null) => v == null ? "-" : String(Math.round(v))
const RANGES = [{ key: "1m", label: "1개월" }, { key: "3m", label: "3개월" }, { key: "1y", label: "1년" }, { key: "3y", label: "3년" }] as const
const RANGE_SUB: Record<string, string> = { "1m": "1개월 전 = 100", "3m": "3개월 전 = 100", "1y": "1년 전 = 100", "3y": "3년 전 = 100" }
const DOC_KIND: Record<UsSectorDocType, string> = { blog: "블로그", youtube: "유튜브", scrap: "스크랩", web: "웹", transcript: "컨콜", earnings_release: "실적 발표" }
const DOC_FILTERS = [{ key: "all", label: "전체" }, { key: "earnings", label: "컨콜·실적" }, { key: "research", label: "리서치" }, { key: "youtube", label: "유튜브" }] as const
const DOC_MATCH: Record<string, UsSectorDocType[]> = { earnings: ["transcript", "earnings_release"], research: ["scrap", "web"], youtube: ["youtube"] }
const PER = 20

function etfTip(d: UsSectorMarket, parentName: string | null) {
  return `${d.full_name}(${d.ticker}) — 이 ${d.parent ? "업종" : "섹터"}의 대표지수로 쓰는 ETF입니다.${parentName ? ` 상위 섹터는 ${parentName}(${d.parent})입니다.` : ""} 비교 지수는 S&P500 ETF(SPY)입니다.`
}

/**
 * 산업 › 섹터 화면 · 미국 (/industry/us/:ticker, ia-redesign §4.36, 시안 Sector-US-Overview).
 * 위치 '섹터 지도 · 미국 › 상위 GICS › 업종' → 머리(이름 · ETF 정식 이름·티커 ⓘ · 종가 · 1일 · 1개월 · 내 커버리지 수 · RS 배지 · 구역)
 * → 탭 개요 · 종목(내 커버리지) · 이 산업의 데이터(URL ?tab=). Peer 그룹 탭·AI 개괄은 두지 않는다.
 * 개요 띠: ① ETF vs SPY(1개월·3개월·1년·3년, URL range) | 상대강도 4주 + 같은 상위 섹터 안 — 400
 *          ② 내 커버리지 종목 | 주요 자료(URL doc) — 560 · ③ 이 산업의 데이터 카드 줄. 칸 높이 고정, 넘침은 칸 안 스크롤.
 */
export default function UsSectorPage() {
  const { ticker: raw = "" } = useParams()
  const ticker = raw.toUpperCase()
  const [rawTab, setTab] = useUrlParam("tab", "overview")
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? rawTab as Tab : "overview"
  const q = useUsSectorDetail(ticker)
  const d = q.data
  const notFound = q.isError && toApiError(q.error).status === 404
  return <PageLayout mode="document">
    <div className="flex flex-col gap-2.5">
      <nav aria-label="위치" className="text-[12.5px] text-ink-3">
        <Link to="/industry?market=us" className="text-ink-2 hover:text-ink">섹터 지도 · 미국</Link>
        {d?.parent && <> › <Link to={usSectorPath(d.parent)} className="text-ink-2 hover:text-ink">{d.parent_name}</Link></>} › {d?.name ?? ticker}
      </nav>
      {d ? <Head d={d} coverage={d.members.length} /> : <div className="flex min-h-[44px] flex-wrap items-end gap-4">
        <h1 className="font-display text-page font-normal tracking-[-0.01em] max-md:text-[26px]">{ticker}</h1>
        {!q.isError && <><Skeleton className="h-6 w-40" /><Skeleton className="h-6 w-56" /></>}
      </div>}
      <Tabs value={tab} onValueChange={setTab} className="min-w-0">
        <div className="-mx-1 overflow-x-auto border-b px-1 [scrollbar-width:none]">
          <TabsList variant="line" aria-label="섹터 탭" className="h-10 gap-[18px] p-0">
            {([["overview", "개요", null], ["stocks", "종목", d?.members.length], ["data", "이 산업의 데이터", d?.data_links.length]] as const).map(([k, label, n]) =>
              <TabsTrigger key={k} value={k} className="h-10 flex-none px-0.5 text-sm data-active:font-semibold">{label}{n != null && <span className="font-mono text-[11.5px] font-normal text-ink-3">{formatNumber(n)}</span>}</TabsTrigger>)}
          </TabsList>
        </div>
      </Tabs>
    </div>
    <div className="mt-4">
      {notFound ? <div role="status" className="space-y-2 border p-6 text-sm"><p>없는 미국 섹터입니다.</p><Link to="/industry?market=us" className="font-semibold hover:underline">미국 섹터 지도로 가기 ›</Link></div>
        : q.isError && !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        : tab === "stocks" ? <StocksTab q={q} />
        : tab === "data" ? <DataTab q={q} />
        : <div className="flex flex-col gap-4">
          <Band label="대표지수와 상대강도" cells={[[8, <IndexCard key="i" q={q} />], [4, <RsCard key="r" q={q} />]]} />
          <Band label="내 커버리지와 주요 자료" cells={[[7, <MembersCard key="m" q={q} />], [5, <DocsCard key="d" q={q} />]]} />
          <DataCard q={q} />
        </div>}
    </div>
  </PageLayout>
}

export function Head({ d, coverage }: { d: UsSectorMarket; coverage?: number }) {
  return <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
    <h1 className="font-display text-page leading-[1.2] font-normal tracking-[-0.01em] max-md:text-[26px]">{d.name}</h1>
    <span className="inline-flex items-center gap-1 self-center pt-2 text-[13px] text-ink-2">
      <span className="truncate max-sm:max-w-[220px]">{d.full_name}</span><span className="font-mono text-ink-3">{d.ticker}</span>
      <InfoTip label="대표지수 설명">{etfTip(d, d.parent_name)}</InfoTip>
    </span>
    <span className="font-display text-[22px] tabular-nums">{formatStockPrice(d.last, "us")}</span>
    <span className="font-mono text-sm tabular-nums"><span className={tone(d.chg_1d)}>{formatPercent(d.chg_1d, 2)}</span> <span className="text-ink-3">·</span> <span className={tone(d.ret_1m)}>1개월 {formatPercent(d.ret_1m)}</span></span>
    <span className="text-[12.5px] text-ink-3">{coverage != null && <>내 커버리지 {formatNumber(coverage)}종목 · </>}{mmdd(d.last_date)}</span>
    <span className="flex flex-wrap gap-1.5">
      <Chip kind={(d.rs_long ?? 0) >= 50 ? "up" : "down"}>장기 RS {rsText(d.rs_long)}</Chip>
      <Chip kind={(d.rs_short ?? 0) >= 50 ? "up" : "down"}>단기 RS {rsText(d.rs_short)}</Chip>
      {d.zone && <Chip kind="warn">{d.zone}</Chip>}
    </span>
  </div>
}

function State<T extends UsSectorMarket>({ q, rows, message, children }: { q: MarketQuery<T>; rows?: number; message: string; children: (d: T) => React.ReactNode }) {
  if (q.data) return <>{children(q.data)}</>
  return q.isError ? <BlockError message={message} error={q.error} onRetry={() => void q.refetch()} /> : <FillSkeleton rows={rows} />
}

export function IndexCard({ q }: { q: MarketQuery }) {
  const [range, setRange] = useUrlParam("range", "1y")
  const d = q.data
  const pts = d ? slice(d.series, range) : []
  const r = rangeReturns(pts)
  return <MarketCard band="sectorChart" label="sector.us.index">
    <BlockHead section title={d ? `대표지수 · ${d.full_name}` : "대표지수"} info={d ? etfTip(d, d.parent_name) : undefined}
      sub={d ? `${d.ticker} · ${RANGE_SUB[range] ?? ""}` : " "} />
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
      <div className="flex gap-3.5 text-xs text-ink-2">
        <span><span aria-hidden className="mr-1.5 inline-block h-0.5 w-3.5 bg-up align-middle" />{d?.ticker ?? "ETF"} <span className={cn("font-mono", tone(r.v))}>{formatPercent(r.v)}</span></span>
        <span><span aria-hidden className="mr-1.5 inline-block w-3.5 border-t border-dashed border-ink-3 align-middle" />S&amp;P500(SPY) <span className={cn("font-mono", tone(r.k))}>{formatPercent(r.k)}</span></span>
      </div>
      <Seg label="기간" value={range} items={RANGES.map(x => ({ key: x.key, label: x.label }))} onChange={setRange} />
    </div>
    <State q={q} rows={8} message="대표지수를 불러오지 못했습니다">{() => pts.length < 2
      ? <FillNote>ETF 시세가 쌓이면 나타납니다.</FillNote>
      : <SectorIndexChart points={pts} label={`${d!.ticker}와 SPY, ${RANGE_SUB[range]}`} className="min-h-0 flex-1" />}</State>
  </MarketCard>
}

function Bar({ v, cls }: { v: number | null; cls: string }) {
  return <div className="flex items-center gap-1.5">
    <div className="h-1.5 flex-1 rounded-[3px] bg-chip"><div className={cn("h-1.5 rounded-[3px]", cls)} style={{ width: `${Math.max(2, v ?? 0)}%` }} /></div>
    <span className="w-[26px] text-right font-mono tabular-nums">{rsText(v)}</span>
  </div>
}

export function RsCard({ q }: { q: MarketQuery }) {
  return <MarketCard band="sectorChart" label="sector.us.rs">
    <BlockHead section title="상대강도" info={US_RS_INFO} sub="24개 섹터·업종 중 백분위" />
    <State q={q} rows={8} message="상대강도를 불러오지 못했습니다">{d => {
      const rows = [...[...d.trail].sort((a, b) => b.weeks_ago - a.weeks_ago).map(t => ({ label: `${t.weeks_ago}주 전`, l: t.rs_long, s: t.rs_short })), { label: "지금", l: d.rs_long, s: d.rs_short }]
      const parentName = d.parent ? d.parent_name : d.name
      return <>
        <div className="grid shrink-0 grid-cols-[56px_1fr_1fr] gap-2.5 text-[11.5px] text-ink-3"><span /><span>장기</span><span>단기</span></div>
        <div className="shrink-0">{rows.map(r => <div key={r.label} className="grid grid-cols-[56px_1fr_1fr] items-center gap-2.5 border-b py-1 text-[12.5px]">
          <span className="text-ink-3">{r.label}</span><Bar v={r.l} cls="bg-ink-2" /><Bar v={r.s} cls="bg-down" />
        </div>)}</div>
        <div className="mt-1 flex shrink-0 justify-between text-xs text-ink-3"><span>같은 상위 섹터({parentName}) 안</span><span>1개월 · 3개월</span></div>
        <FillArea aria-label="같은 상위 섹터 안">{d.siblings.map(x => <Link key={x.ticker} to={usSectorPath(x.ticker)}
          className={cn("grid grid-cols-[minmax(0,1fr)_44px_62px_62px] gap-2 border-b py-1.5 text-[12.5px] hover:bg-surface-2", x.ticker === d.ticker && "font-semibold")}>
          <span className="truncate">{x.parent && "↳ "}{x.name}</span>
          <span className="font-mono text-[11.5px] text-ink-3">{x.ticker}</span>
          <span className={cn("text-right font-mono tabular-nums", tone(x.ret_1m))}>{formatPercent(x.ret_1m)}</span>
          <span className={cn("text-right font-mono tabular-nums", tone(x.ret_3m))}>{formatPercent(x.ret_3m)}</span>
        </Link>)}</FillArea>
      </>
    }}</State>
  </MarketCard>
}

const MEMBER_COLS = "grid-cols-[54px_minmax(0,1fr)_minmax(0,120px)_60px_60px_60px_88px] max-md:grid-cols-[48px_minmax(0,1fr)_56px_56px_64px]"

function MembersCard({ q }: { q: Q }) {
  const d = q.data
  return <MarketCard band="sectorText" label="sector.us.members">
    <BlockHead section title="내 커버리지 종목" info={`팔로우 종목 중 Yahoo 분류가 이 ${d?.parent ? "업종" : "섹터"}인 종목입니다. ETF 구성 종목 전체가 아니라 내가 따라가는 종목입니다.`}
      sub={d ? `${d.members.length}종목 · 시가총액 순` : " "} link={d?.members.length ? { to: "?tab=stocks", label: "종목 탭" } : null} />
    <div className={cn("grid shrink-0 gap-2 text-[11.5px] text-ink-3", MEMBER_COLS)}>
      <span>티커</span><span>이름</span><span className="max-md:hidden">업종</span><span className="text-right max-md:hidden">1주</span><span className="text-right">1개월</span><span className="text-right">3개월</span><span className="text-right">3개월 추이</span>
    </div>
    <State q={q} rows={10} message="내 커버리지 종목을 불러오지 못했습니다">{d => !d.members.length
      ? <FillNote>이 섹터·업종에 속한 팔로우 종목이 없습니다.</FillNote>
      : <FillArea aria-label="내 커버리지 종목">{d.members.map(m => <Link key={m.ticker} to={`/us/${m.ticker}`}
        className={cn("grid items-center gap-2 border-b py-[7px] text-[12.5px] hover:bg-surface-2", MEMBER_COLS)}>
        <span className="font-mono font-medium">{m.ticker}</span>
        <span className="truncate">{m.name}</span>
        <span className="truncate text-ink-3 max-md:hidden">{m.industry ?? "-"}</span>
        <span className={cn("text-right font-mono tabular-nums max-md:hidden", tone(m.ret_1w))}>{formatPercent(m.ret_1w)}</span>
        <span className={cn("text-right font-mono tabular-nums", tone(m.ret_1m))}>{formatPercent(m.ret_1m)}</span>
        <span className={cn("text-right font-mono tabular-nums", tone(m.ret_3m))}>{formatPercent(m.ret_3m)}</span>
        <span className="flex justify-end">{m.closes.length > 2 ? <SparkLine data={m.closes} height={22} className="w-[88px] max-md:w-16" /> : <span className="text-ink-3">-</span>}</span>
      </Link>)}</FillArea>}</State>
  </MarketCard>
}

function DocsCard({ q }: { q: Q }) {
  const [f, setF] = useUrlParam("doc", "all")
  const docs = (q.data?.docs ?? []).filter(x => f === "all" || (DOC_MATCH[f] ?? []).includes(x.type))
  return <MarketCard band="sectorText" label="sector.us.docs">
    <BlockHead section title="주요 자료" info="피드에 들어온 자료 중 이 섹터·업종의 내 커버리지 종목이 붙은 것입니다. 여러 종목이 함께 붙은 자료가 먼저입니다. 리서치는 스크랩·웹 자료이고, 텔레그램은 넣지 않습니다."
      sub="최근 10일 · 커버리지 종목이 붙은 자료" />
    <Seg label="자료 종류" value={f} items={DOC_FILTERS.map(x => ({ key: x.key, label: x.label }))} onChange={setF} className="shrink-0 self-start" />
    <State q={q} rows={10} message="주요 자료를 불러오지 못했습니다">{() => !docs.length
      ? <FillNote>최근 10일 이 섹터·업종 자료가 없습니다.</FillNote>
      : <FillArea aria-label="주요 자료">{docs.map(x => <Link key={x.id} to={`/doc/${x.id}`}
        className="grid grid-cols-[60px_minmax(0,1fr)_40px] items-baseline gap-2 border-b py-[9px] hover:bg-surface-2">
        <Chip className="justify-center text-[11px] font-normal">{DOC_KIND[x.type]}</Chip>
        <span className="line-clamp-2 text-[13px] leading-normal">{x.title}</span>
        <span className="text-right font-mono text-[11px] text-ink-3">{mmdd(x.published_at?.slice(0, 10))}</span>
      </Link>)}</FillArea>}</State>
  </MarketCard>
}

const DATA_INFO = "이 섹터·업종과 연결된 화면입니다. 한국 섹터 카드는 같은 업종의 한국 쪽으로 건너갑니다."

function DataCard({ q }: { q: Q }) {
  const d = q.data
  const cards = d?.data_links ?? []
  return <section aria-label="이 산업의 데이터" className="flex flex-col gap-3 rounded-[var(--radius-card)] border bg-card px-[18px] py-4">
    <BlockHead section title="이 산업의 데이터" info={DATA_INFO} sub={d ? `연결 ${cards.length}` : " "} link={cards.length ? { to: "?tab=data", label: "데이터 탭" } : null} />
    {q.isError && !d ? <BlockError message="연결 데이터를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !d ? <div className="grid grid-cols-2 pr-px pb-px lg:grid-cols-4 [&>*]:-mr-px [&>*]:-mb-px">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-[118px] rounded-none border" />)}</div>
      : !cards.length ? <p role="status" className="text-sm text-ink-3">연결된 데이터 화면이 없습니다.</p>
      : <div className="grid grid-cols-1 pr-px pb-px sm:grid-cols-2 lg:grid-cols-4 [&>*]:-mr-px [&>*]:-mb-px">{cards.map(c => <DataLinkCard key={c.kind} c={c} />)}</div>}
  </section>
}

function DataTab({ q }: { q: Q }) {
  const cards = q.data?.data_links ?? []
  return <section aria-label="이 산업의 데이터" className="flex flex-col gap-3 border bg-card px-[18px] py-4">
    <BlockHead section title="이 산업의 데이터" info={DATA_INFO} sub={q.data ? `연결 ${cards.length}` : " "} />
    {q.isError && !q.data ? <BlockError message="연결 데이터를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !q.data ? <div className="grid grid-cols-1 pr-px pb-px sm:grid-cols-2 lg:grid-cols-3 [&>*]:-mr-px [&>*]:-mb-px">{[0, 1, 2].map(i => <Skeleton key={i} className="h-[150px] rounded-none border" />)}</div>
      : !cards.length ? <p role="status" className="py-6 text-sm text-ink-3">연결된 데이터 화면이 없습니다.</p>
      : <div className="grid grid-cols-1 pr-px pb-px sm:grid-cols-2 lg:grid-cols-3 [&>*]:-mr-px [&>*]:-mb-px">{cards.map(c => <DataLinkCard key={c.kind} c={c} big />)}</div>}
  </section>
}

/** 종목 탭 — 내 커버리지 전체(시가총액 순), 20개씩(URL page) */
function StocksTab({ q }: { q: Q }) {
  const [rawPage, setPage] = useUrlParam("page", "1")
  const rows = q.data?.members ?? []
  const p = paged(rows, Math.max(0, (Number(rawPage) || 1) - 1), PER)
  return <MarketCard band="sectorPeers" label="sector.us.stocks">
    <BlockHead section title="내 커버리지 종목" info="팔로우 종목 중 Yahoo 분류로 이 섹터·업종에 속한 종목입니다. 1주는 7일, 1개월·3개월은 21·63거래일 수익률입니다."
      sub={q.data ? `시가총액 순 · ${mmdd(q.data.last_date)}` : " "} />
    {q.isError && !q.data ? <BlockError message="내 커버리지 종목을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !q.data ? <FillSkeleton rows={14} />
      : !rows.length ? <FillNote>이 섹터·업종에 속한 팔로우 종목이 없습니다.</FillNote>
      : <>
        <FillArea aria-label="내 커버리지 종목">
          <Table className="text-[13px]">
            <TableHeader><TableRow>
              <TableHead className="w-10 text-[12px]">#</TableHead><TableHead className="text-[12px]">종목</TableHead>
              <TableHead className="text-[12px] max-sm:hidden">업종</TableHead><TableHead className="text-right text-[12px]">시총</TableHead>
              <TableHead className="text-right text-[12px] max-sm:hidden">1주</TableHead><TableHead className="text-right text-[12px]">1개월</TableHead>
              <TableHead className="text-right text-[12px]">3개월</TableHead><TableHead className="text-right text-[12px] max-sm:hidden">3개월 추이</TableHead>
            </TableRow></TableHeader>
            <TableBody>{p.rows.map((m, i) => <TableRow key={m.ticker}>
              <TableCell className="font-mono text-ink-3 tabular-nums">{p.from + i}</TableCell>
              <TableCell className="max-w-[220px] truncate"><Link to={`/us/${m.ticker}`} className="hover:underline"><span className="font-mono font-medium">{m.ticker}</span> <span className="text-ink-2">{m.name}</span></Link></TableCell>
              <TableCell className="max-w-[160px] truncate text-ink-3 max-sm:hidden">{m.industry ?? "-"}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{m.market_cap == null ? "-" : formatUsd(m.market_cap)}</TableCell>
              <TableCell className={cn("text-right font-mono tabular-nums max-sm:hidden", tone(m.ret_1w))}>{formatPercent(m.ret_1w)}</TableCell>
              <TableCell className={cn("text-right font-mono tabular-nums", tone(m.ret_1m))}>{formatPercent(m.ret_1m)}</TableCell>
              <TableCell className={cn("text-right font-mono tabular-nums", tone(m.ret_3m))}>{formatPercent(m.ret_3m)}</TableCell>
              <TableCell className="max-sm:hidden"><span className="flex justify-end">{m.closes.length > 2 ? <SparkLine data={m.closes} height={22} className="w-[88px]" /> : "-"}</span></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </FillArea>
        <PagerBar {...p} onPage={n => setPage(String(n + 1))} label="내 커버리지 종목 페이지" />
      </>}
  </MarketCard>
}
