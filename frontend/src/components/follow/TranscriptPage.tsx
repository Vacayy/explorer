import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { track } from "@/lib/usage"
import { Link, Navigate, useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Search, Sparkles, ChevronRight } from "lucide-react"
import api from "@/api/client"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { PageContainer } from "@/components/shared/PageContainer"
import { Markdown } from "@/components/shared/Markdown"
import CollectTranscripts from "@/components/follow/CollectTranscripts"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { useMediaQuery, MOBILE_QUERY } from "@/hooks/useMediaQuery"
import { TranscriptTabs } from "@/components/follow/TranscriptTabs"
import { proxiesUrl } from "@/lib/judgment"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { MomentumStrip } from "@/components/follow/CallMomentumPanel"
import { RecentCalls } from "@/components/follow/RecentCalls"
import { CallReaction } from "@/components/follow/CallReaction"
import { TranscriptTickerActions } from "@/components/follow/TranscriptTickerActions"
import { SeasonView } from "@/components/follow/season/SeasonView"
import { KrSeasonView } from "@/components/follow/season/KrSeasonView"
import { seasonMarket } from "@/components/follow/season/SeasonHeader"
import { SectorView } from "@/components/follow/season/SectorView"
import { CallWindowChart, ChainCharts, ChainHeaderLinks, HistoryCard, IssuesRow, StagesCard, currentHistory, fyShort } from "@/components/follow/season/ChainSections"
import { WEIGHT } from "@/components/follow/season/seasonUi"
import { InfoTip } from "@/components/shared/InfoTip"
import { formatPp } from "@/utils/format"
import { useChain } from "@/hooks/useTranscripts"
import { QueryState } from "@/components/shared/QueryState"
import { cn } from "@/lib/utils"

/**
 * /follow/transcripts — 미국 기업 실적 컨콜 전용 페이지 (D-061, 2분할 브라우저).
 * 좌: 팔로우 기업 그룹 리스트(= 구독 관리) · 우: 선택 콜의 LLM 핵심 정리 → 원문 전문.
 * URL(?t=transcript_id)이 상태 소스. 정리는 POST compute(멱등·수 분)로 분리 생성.
 */
const GROUP_LABEL: Record<string, string> = {
  M7: "M7", hyperscaler: "하이퍼스케일러", nasdaq: "반도체·나스닥",
  "ai-datacenter": "AI 데이터센터", space: "우주", energy: "에너지",
  cpo: "CPO", software: "소프트웨어", web3: "Web3",
}
const GROUP_ORDER = ["M7", "hyperscaler", "nasdaq", "ai-datacenter", "space", "energy", "cpo", "software", "web3"]

interface LatestCall { transcript_id: number; fiscal_year: number | null; fiscal_period: string | null; cy?: string | null; call_date: string | null; has_digest: boolean }
interface FollowRow {
  ticker: string; company_name: string; group_label: string | null; n_calls: number; latest: LatestCall | null
  last_report_date?: string | null; next_report_date?: string | null; calendar_checked_at?: string | null
  market_cap?: number | null; category?: string | null; latest_results_date?: string | null; season_updated?: boolean
  ko_names?: string[]
}
type RailSort = "cap" | "category" | "recent"
const RAIL_SORTS: { value: RailSort; label: string }[] = [{ value: "cap", label: "시가총액" }, { value: "category", label: "사업분류" }, { value: "recent", label: "최근 발표" }]
/** 지금 실적 시즌이 보고하는 분기(10~12월 → 3Q) — 백엔드 call_momentum.season과 같은 규칙 */
const seasonQ = () => { const q = Math.floor(new Date().getMonth() / 3); return q === 0 ? 4 : q }
const usd = (v?: number | null) => v == null ? "–" : v >= 1e12 ? `$${(v / 1e12).toFixed(1)}T` : `$${Math.round(v / 1e9)}B`
interface Quarter { transcript_id: number; fiscal_year: number | null; fiscal_period: string | null; cy?: string | null; call_date: string | null; has_digest: boolean }
interface TxNode { id: number; name: string; type: string; link_type: string }
interface TxEdge { rel_type: string; effect_direction: string | null; from: string; from_id: number; from_type: string; to: string; to_id: number; to_type: string }
interface Detail { transcript_id: number; ticker: string; company_name: string; fiscal_year: number | null; fiscal_period: string | null; cy?: string | null; call_date: string | null; digest: string | null; body: string; nodes?: TxNode[]; causal_edges?: TxEdge[] }

const NODE_LABEL: Record<string, string> = {
  company: "기업", sector: "섹터", theme: "테마", person: "인물",
  macro: "매크로", policy: "정책", event: "사건", industry: "산업", topic: "토픽",
}

/* 온톨로지 딥링크 칩 — 클릭 시 전역 인과 그래프의 그 노드로 초점 (?focus=id, D-089) */
function OntoChip({ id, name, type }: { id: number; name: string; type: string }) {
  return (
    <Link to={`/knowledge/ontology?focus=${id}`} title="온톨로지 그래프에서 이 노드 보기"
      className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs hover:border-primary hover:bg-primary/5 transition-colors">
      <span className="text-[9px] text-muted-foreground">{NODE_LABEL[type] ?? type}</span>
      <span className="font-medium">{name}</span>
    </Link>
  )
}

const periodOf = (y: number | null, p: string | null) => `FY${y ?? "?"} ${p ?? ""}`.trim()
/** 기본 표시는 달력분기(CY) — 회사 회계분기(FY)는 보조. CY를 못 구하면(결산 월 미상) FY 그대로 */
const quarterLabel = (cy: string | null | undefined, y: number | null, p: string | null) => cy ?? periodOf(y, p)
const shortQuarter = (cy: string | null | undefined, p: string | null) => cy ? `${cy.slice(4, 6)}${cy.slice(-2)}` : (p ?? "–")   // 26Q2

/** 발표일까지 남은 일수 (오늘 0, 미래 양수, 지난 날 음수) */
const ddayLabel = (n: number) => (n === 0 ? "오늘" : n > 0 ? `D-${n}` : `D+${-n}`)
function daysUntil(iso?: string | null): number | null {
  if (!iso) return null
  const d = new Date(iso + "T00:00:00")
  if (Number.isNaN(d.getTime())) return null
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - today.getTime()) / 86_400_000)
}
const mmdd = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`

export default function TranscriptPage() {
  const [params, setParams] = useSearchParams()
  const selectedId = params.get("t")
  // 옛 '실적 모멘텀' 링크(?view=momentum)는 실적 시즌으로 — 모멘텀은 시즌 보기 안의 한 섹션
  const rawView = params.get("view") === "momentum" ? "season" : params.get("view")
  const view = (["season"] as const).find((v) => v === rawView) ?? "calls"
  const sector = params.get("sector")
  const railSort: RailSort = (["cap", "category", "recent"] as const).find((v) => v === params.get("rail")) ?? "cap"
  const qc = useQueryClient()

  const { data: follows = [], isLoading, isError, refetch } = useQuery(
    apiQuery<FollowRow[]>({ key: ["spine", "transcript", "follow"], url: "/api/spine/transcript/follow", staleTime: STALE.short }),
  )

  const seed = useMutation({
    mutationFn: () => api.post("/api/spine/transcript/seed").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "transcript", "follow"] }),
  })

  const refreshCal = useMutation({
    mutationFn: () => api.post("/api/spine/transcript/calendar/refresh").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "transcript", "follow"] }),
  })

  const mobile = useMediaQuery(MOBILE_QUERY)
  // 기업 목록에서 고르면 기록을 남긴다(뒤로 가기 = 목록), 상세 안에서 분기·기업을 바꾸면 교체
  const selectId = (id: number) => setParams({ t: String(id) }, { replace: !!selectedId })

  // 옛 프록시 보기 → Thesis › 내 판단 '지표 보드'(ia-redesign §10.6)
  if (rawView === "proxies") return <Navigate to={proxiesUrl(`?${params.toString()}`)} replace />
  const tabs = <TranscriptTabs value={view} />
  // 실적 시즌은 팔로우 목록을 기다리지 않는다 — 시즌 응답 하나로 그린다
  if (view === "season") {
    if (seasonMarket(params) === "kr") return <PageContainer><KrSeasonView tabs={tabs} /></PageContainer>
    return <PageContainer>{sector ? <>{tabs}<SectorView key={sector} sectorKey={sector} /></> : <SeasonView tabs={tabs} />}</PageContainer>
  }
  if (isLoading) return <TranscriptSkeleton />
  if (isError) return <PageContainer><ErrorState onRetry={() => refetch()} /></PageContainer>

  const withCalls = follows.filter((f) => f.n_calls > 0)
  // 기본 선택: URL에 없으면 콜 있는 첫 기업의 최신
  const effectiveId = selectedId ?? (withCalls[0]?.latest?.transcript_id ? String(withCalls[0].latest!.transcript_id) : null)

  const header = (
    <div className="flex flex-col gap-0.5">
      <h1 className="font-display text-page font-normal tracking-[-0.02em] max-md:text-[26px] max-md:leading-[1.3]">컨콜</h1>
      <span className="text-caption text-muted-foreground">미국 기업 실적 컨퍼런스콜 · 팔로우 {follows.length}</span>
    </div>
  )

  const railFor = (onPick: (id: number) => void) => follows.length === 0 ? (
    <div className="p-3 space-y-3">
      <p className="text-xs text-muted-foreground">팔로우가 비어 있습니다. 기본 세트를 불러오세요.</p>
      <Button size="sm" onClick={() => seed.mutate()} disabled={seed.isPending}>
        {seed.isPending ? "불러오는 중…" : "기본 세트 팔로우"}
      </Button>
    </div>
  ) : (
    <FollowRail follows={follows} sort={railSort} effectiveId={effectiveId} onSelect={onPick}
      onSort={(v) => setParams((prev) => { const n = new URLSearchParams(prev); n.set("rail", v); return n }, { replace: true })} />
  )
  // 기업 목록(?t= 없음): 맨 위 모멘텀 한 줄·수집·최근 받은 컨콜·곧 발표 + 기업 목록. 모바일은 목록만(상세는 기업을 고른 뒤).
  // 콜 상세(?t=): 기업 목록 | 상세(시안 Call-Detail). 모바일은 기업 고르기를 시트로(시안 Mobile-Call).
  const listing = !selectedId
  return (
    <PageContainer>
      {/* 폰 콜 상세는 시안(Mobile-Call)대로 제목 없이 보기 칩부터 */}
      {!(mobile && !listing) && header}
      {tabs}
      {listing && <>
        {/* 이번 시즌 실적 발언 모멘텀 — 0클릭으로 보이게 맨 위 한 줄 (전체는 '실적 시즌' 보기) */}
        <MomentumStrip />
        {/* 수집 직접 트리거 — cron만 기다리지 않고 지금 돌린다 (D-121) */}
        <CollectTranscripts />
        <RecentCalls onSelect={selectId} selectedId={selectedId} />
        <UpcomingLink follows={follows} onRefresh={() => refreshCal.mutate()} refreshing={refreshCal.isPending} />
      </>}
      {mobile ? (
        listing ? (
          <Card><CardContent className="p-2">{railFor(selectId)}</CardContent></Card>
        ) : (
          <MobileCallDetail key={effectiveId} transcriptId={Number(effectiveId)} onSelect={selectId} rail={railFor} />
        )
      ) : (
      <div className="surface-grid grid grid-cols-1 md:grid-cols-[240px_1fr] items-start">
        {/* 좌 레일 — 팔로우 기업 목록 (구독 관리 겸용) */}
        <Card className="md:sticky md:top-16">
          <CardContent className="p-2 max-h-[45vh] md:max-h-[70vh] overflow-y-auto">{railFor(selectId)}</CardContent>
        </Card>

        {/* 우 본문 — 선택 콜 상세 */}
        <div className="min-w-0">
          {effectiveId ? (
            <DetailPanel key={effectiveId} transcriptId={Number(effectiveId)} onSelect={selectId} />
          ) : (
            <Card><CardContent className="py-16">
              <EmptyState message="아직 수집된 컨콜이 없습니다. 관리자에서 '컨콜 수집'을 실행하거나 기업을 팔로우해 주세요." />
            </CardContent></Card>
          )}
        </div>
      </div>
      )}
    </PageContainer>
  )
}

/* ---------- 곧 발표 → 실적 시즌 발표 캘린더로 (D-302: 목록 블록은 캘린더와 겹쳐 한 줄 연결만 남긴다) ---------- */
function UpcomingLink({ follows, onRefresh, refreshing }: { follows: FollowRow[]; onRefresh: () => void; refreshing: boolean }) {
  const soon = follows.filter((f) => { const d = daysUntil(f.next_report_date); return d != null && d >= 0 && d <= 7 }).length
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm" data-upcoming-link>
        <span className="text-xs font-medium text-muted-foreground">곧 발표</span>
        <span>7일 안 <b className="tabular-nums">{soon}</b>곳</span>
        <Link to="/follow/transcripts?view=season#calendar" className="inline-flex items-center gap-0.5 text-primary hover:underline">
          발표 캘린더에서 보기<ChevronRight className="size-3.5" />
        </Link>
        <Button variant="ghost" size="xs" className="ml-auto" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "갱신 중…(수십초)" : "발표일 갱신"}
        </Button>
      </CardContent>
    </Card>
  )
}

/* ---------- 좌 레일: 정렬 탭 + 기업 검색(티커·영문명·한글 별칭) ---------- */
function FollowRail({ follows, sort, onSort, effectiveId, onSelect }: {
  follows: FollowRow[]; sort: RailSort; onSort: (v: RailSort) => void; effectiveId: string | null; onSelect: (id: number) => void
}) {
  const [query, setQuery] = useState("")
  const q = query.trim().toLowerCase()
  const shown = useMemo(() => !q ? follows : follows.filter((f) =>
    [f.ticker, f.company_name, ...(f.ko_names ?? [])].some((name) => name.toLowerCase().includes(q))), [follows, q])
  return (
    <>
      {/* 240px 레일에 세 탭이 들어가도록 칸을 균등 분할하고 글자·여백을 줄인다 */}
      <SegmentTabs tabs={RAIL_SORTS} value={sort} onChange={(v) => onSort(v as RailSort)} className="mb-2 w-full *:h-8 *:min-w-0 *:flex-1 *:px-1 *:text-xs" />
      <div className="relative mb-2">
        <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="기업 검색 (NVDA·엔비디아)" aria-label="팔로우 기업 검색" className="h-8 pl-7 text-xs" />
      </div>
      {shown.length === 0 ? <p className="px-2 py-3 text-xs text-muted-foreground">‘{query.trim()}’에 맞는 팔로우 기업이 없습니다.</p>
        : sort === "category"
          ? <GroupedRail follows={shown} effectiveId={effectiveId} onSelect={onSelect} />
          : <FlatRail follows={shown} sort={sort} effectiveId={effectiveId} onSelect={onSelect} />}
    </>
  )
}

/* ---------- 좌 레일: 그룹별 기업 리스트 ---------- */
function GroupedRail({ follows, effectiveId, onSelect }: {
  follows: FollowRow[]; effectiveId: string | null; onSelect: (id: number) => void
}) {
  const byGroup = useMemo(() => {
    const m = new Map<string, FollowRow[]>()
    for (const f of [...follows].sort((a, b) => (b.market_cap ?? 0) - (a.market_cap ?? 0))) {
      const g = f.category ?? f.group_label ?? "기타"
      if (!m.has(g)) m.set(g, [])
      m.get(g)!.push(f)
    }
    return m
  }, [follows])
  const groups = [...GROUP_ORDER.filter((g) => byGroup.has(g)), ...[...byGroup.keys()].filter((g) => !GROUP_ORDER.includes(g))]

  return (
    <div className="space-y-1">
      {groups.map((g) => (
        <Collapsible key={g} defaultOpen>
          <CollapsibleTrigger className="flex w-full items-center gap-1 px-2 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground">
            <ChevronRight className="h-3 w-3 transition-transform data-[state=open]:rotate-90" />
            {GROUP_LABEL[g] ?? g}
          </CollapsibleTrigger>
          <CollapsibleContent className="pl-1">
            {byGroup.get(g)!.map((f) => <RailRow key={f.ticker} f={f} effectiveId={effectiveId} onSelect={onSelect} />)}
          </CollapsibleContent>
        </Collapsible>
      ))}
    </div>
  )
}

/* ---------- 좌 레일: 시가총액순 / 최근 발표순 (평평한 목록) ---------- */
function FlatRail({ follows, sort, effectiveId, onSelect }: {
  follows: FollowRow[]; sort: "cap" | "recent"; effectiveId: string | null; onSelect: (id: number) => void
}) {
  const rows = useMemo(() => [...follows].sort((a, b) => sort === "cap"
    ? (b.market_cap ?? 0) - (a.market_cap ?? 0)
    : (b.latest_results_date ?? "").localeCompare(a.latest_results_date ?? "")), [follows, sort])
  return <div className="space-y-0.5">{rows.map((f) => <RailRow key={f.ticker} f={f} effectiveId={effectiveId} onSelect={onSelect}
    meta={sort === "cap" ? usd(f.market_cap) : f.latest_results_date ? mmdd(f.latest_results_date) : "–"} />)}</div>
}

function RailRow({ f, effectiveId, onSelect, meta }: { f: FollowRow; effectiveId: string | null; onSelect: (id: number) => void; meta?: string }) {
  const active = f.latest && String(f.latest.transcript_id) === effectiveId
  const dd = daysUntil(f.next_report_date)
  const imminent = dd != null && dd >= 0 && dd <= 14
  return (
    <Button variant="ghost" onClick={() => f.latest && onSelect(f.latest.transcript_id)} disabled={!f.latest}
      title={f.season_updated ? `이번 시즌 실적 발표 ${f.latest_results_date}` : undefined}
      className={cn("h-auto w-full justify-start gap-2 rounded-md px-2 py-1.5 text-left text-sm font-normal",
        active && "bg-accent text-accent-foreground font-semibold", !f.latest && "opacity-40")}>
      <span className="font-medium tabular-nums">{f.ticker}</span>
      <span className="truncate text-xs text-muted-foreground flex-1">{f.company_name}</span>
      {f.season_updated && <span className="shrink-0 rounded bg-up/10 px-1 text-[9px] font-medium text-up-ink">{seasonQ()}Q 실적</span>}
      {imminent && !f.season_updated && (
        <span className="text-[9px] font-medium tabular-nums shrink-0 rounded bg-primary/10 px-1 text-primary" title={`다음 실적 ${f.next_report_date}`}>
          {ddayLabel(dd!)}
        </span>
      )}
      {meta && <span className="text-[10px] tabular-nums text-muted-foreground shrink-0">{meta}</span>}
      <span className="text-[10px] tabular-nums text-muted-foreground shrink-0" title={f.latest ? periodOf(f.latest.fiscal_year, f.latest.fiscal_period) : undefined}>
        {f.latest ? shortQuarter(f.latest.cy, f.latest.fiscal_period) : "–"}</span>
    </Button>
  )
}

/* ---------- 우 본문: 콜 상세 (시안 Call-Detail) — 머리(회사·분기 세그먼트) · 발표 창 차트 · 칸 넷 · 쟁점 · 분기별 기록 · 펼치기 ---------- */
function DetailPanel({ transcriptId, onSelect }: { transcriptId: number; onSelect: (id: number) => void }) {
  const { data, isLoading, isError, refetch } = useQuery(detailQuery(transcriptId))
  const chain = useChain(transcriptId)

  if (isLoading) return <Card><CardContent className="py-3 space-y-3"><Skeleton className="h-5 w-48" /><Skeleton className="h-24 w-full" /></CardContent></Card>
  if (isError || !data) return <Card><CardContent className="py-10"><ErrorState onRetry={() => refetch()} /></CardContent></Card>

  const headline = chain.data?.reaction_meta?.headline

  return (
    <div className="surface-stack">
      <Card>
        <CardContent className="flex flex-col gap-3.5 p-[18px]">
          {/* 머리 — 회사·티커·섹터·핵심, 오른쪽 끝 분기 세그먼트(오래된 분기 → 최신이 오른쪽) */}
          <div className="flex flex-wrap items-baseline justify-between gap-2.5">
            <div className="flex min-w-0 flex-wrap items-baseline gap-2.5">
              <h2 className="truncate font-display text-[26px] font-normal leading-tight">{data.company_name}</h2>
              <Badge variant="outline">{data.ticker}</Badge>
              {chain.data && <ChainHeaderLinks chain={chain.data} />}
            </div>
            <QuarterTabs ticker={data.ticker} current={transcriptId} onSelect={onSelect} />
          </div>
          <span className="text-[12.5px] text-ink-3">{callMeta(data, chain.data?.etf)}</span>
          {headline && <p className="text-base font-semibold leading-normal text-pretty">{headline}</p>}
          <TranscriptTickerActions ticker={data.ticker} currentId={transcriptId} onSelect={onSelect}
            extra={<Button variant="ghost" size="sm" asChild><Link to={`/us/${data.ticker}`} title="이 종목의 도시에(시세·밸류·투자 렌즈) 보기">도시에<ChevronRight /></Link></Button>} />
          {/* 발표 창 D−6~D+3 — 일별 긴 차트·거래량·자료 언급은 아래 '더 보기' */}
          <QueryState query={chain} isEmpty={() => false} loading={<Skeleton className="aspect-[16/5] w-full rounded-card" />}>
            {(c) => <CallWindowChart chain={c} />}
          </QueryState>
        </CardContent>
      </Card>

      {chain.data && <>
        <StagesCard chain={chain.data} transcriptId={transcriptId} />
        <IssuesRow chain={chain.data} />
        <HistoryCard chain={chain.data} transcriptId={transcriptId} onSelect={onSelect} />
      </>}

      <Card><CardContent className="p-4"><DetailFolds data={data} transcriptId={transcriptId} /></CardContent></Card>
    </div>
  )
}

const detailQuery = (transcriptId: number) =>
  apiQuery<Detail>({ key: ["spine", "transcript", "detail", transcriptId], url: `/api/spine/transcript/detail/${transcriptId}`, staleTime: STALE.medium })
/** 'CY2026 Q3 · 10/28 발표 · 비교 QQQ' */
const callMeta = (d: Detail, etf?: string) =>
  [quarterLabel(d.cy, d.fiscal_year, d.fiscal_period), d.call_date && `${mmdd(d.call_date)} 발표`, etf && `비교 ${etf}`].filter(Boolean).join(" · ")
/** 분기 라벨 — 시안 'FY26 Q3' (회계연도를 모르면 달력분기) */
const fyLabel = (q: { fiscal_year: number | null; fiscal_period: string | null; cy?: string | null }) =>
  q.fiscal_year != null ? `FY${String(q.fiscal_year).slice(2)} ${q.fiscal_period ?? ""}`.trim() : quarterLabel(q.cy, q.fiscal_year, q.fiscal_period)

/** 펼치기 묶음 — 기간 전체 차트 · 핵심 정리 · 시장 반응 전문 · 온톨로지 · 원문 (기본 접힘) */
function DetailFolds({ data, transcriptId }: { data: Detail; transcriptId: number }) {
  const chain = useChain(transcriptId)
  const [wantDigest, setWantDigest] = useState(false)
  const computed = useQuery({
    ...apiComputeQuery<Detail>({ key: ["spine", "transcript", "digest", transcriptId], url: `/api/spine/transcript/detail/${transcriptId}/digest`, timeout: 300_000, enabled: wantDigest }),
  })
  const digest = computed.data?.digest ?? data.digest
  const hasOnto = (data.nodes?.length ?? 0) > 0 || (data.causal_edges?.length ?? 0) > 0
  return (
    <div className="flex flex-col">
      {chain.data && chain.data.series.length > 0 && (
        <Fold label="더 보기 · 기간 전체 주가·거래량·자료 언급"><ChainCharts chain={chain.data} /></Fold>
      )}
      <Fold label="핵심 정리 (컨콜 전체)">
        {digest ? (
          <div className="bg-muted/40 px-4 py-3"><Markdown>{digest}</Markdown></div>
        ) : computed.isFetching ? (
          <div className="bg-muted/40 px-4 py-3 space-y-2">
            <Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" />
            <p className="text-xs text-muted-foreground">LLM이 컨콜을 정리하는 중… (수 분 소요)</p>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => { track('action', 'digest.make', { entity: transcriptId }); setWantDigest(true) }}>
            <Sparkles className="h-3.5 w-3.5" /> 핵심 정리 생성 (LLM)
          </Button>
        )}
      </Fold>
      {/* 시장 반응 — 발표일~7일 내 자료·주가·헤드라인 */}
      <Fold label="시장 반응 정리 전문·출처">
        <CallReaction transcriptId={transcriptId} callDate={data.call_date} />
      </Fold>
      {/* 온톨로지 연결 (D-089) — 이 콜이 편입된 노드·인과, 클릭 시 그래프로 */}
      {hasOnto && (
        <Fold label="온톨로지 연결">
          {(data.nodes?.length ?? 0) > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {data.nodes!.map((n) => <OntoChip key={n.id} id={n.id} name={n.name} type={n.type} />)}
            </div>
          )}
          {(data.causal_edges?.length ?? 0) > 0 && (
            <ul className="space-y-1">
              {data.causal_edges!.map((e, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1">
                  <OntoChip id={e.from_id} name={e.from} type={e.from_type} />
                  <span className="text-[10px] text-muted-foreground">{e.rel_type === "BENEFITS_FROM" ? "← 수혜" : "→ 인과"}</span>
                  <OntoChip id={e.to_id} name={e.to} type={e.to_type} />
                </li>
              ))}
            </ul>
          )}
        </Fold>
      )}
      <Fold label="원문 전문">
        <div className="max-h-[60vh] overflow-y-auto border px-4 py-3 text-sm">
          <Markdown>{data.body}</Markdown>
        </div>
      </Fold>
    </div>
  )
}

/** 펼치기 한 줄 — 기본 접힘, 줄마다 윗선(시안 details) */
function Fold({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Collapsible className="border-t border-line first:border-t-0">
      <CollapsibleTrigger className="group flex w-full items-center gap-1.5 py-2.5 text-left text-[13.5px] font-medium hover:text-ink-2">
        <ChevronRight className="size-3.5 text-ink-3 transition-transform group-data-[state=open]:rotate-90" />{label}
      </CollapsibleTrigger>
      <CollapsibleContent className="pb-3">{children}</CollapsibleContent>
    </Collapsible>
  )
}

/** 분기 세그먼트 — API는 최신 먼저라 뒤집어 최신 분기가 오른쪽, 최근 여섯 분기까지 */
function useQuarters(ticker: string) {
  return useQuery(apiQuery<Quarter[]>({ key: ["spine", "transcript", "company", ticker], url: `/api/spine/transcript/company/${ticker}`, staleTime: STALE.short }))
}
function QuarterTabs({ ticker, current, onSelect, compact = false }: { ticker: string; current: number; onSelect: (id: number) => void; compact?: boolean }) {
  const { data: quarters = [] } = useQuarters(ticker)
  // 폰 칩 줄은 가로 스크롤 — 고른 분기가 보이게 그 칩으로 민다
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!compact) return
    scroller.current?.querySelector<HTMLElement>("[data-state=on]")?.scrollIntoView({ block: "nearest", inline: "nearest" })
  }, [compact, current, quarters.length])
  if (quarters.length <= 1) return null
  const shown = [...quarters].slice(0, compact ? quarters.length : 6).reverse()
  return (
    <div ref={scroller} className={cn(compact && "-mx-4 overflow-x-auto px-4 [scrollbar-width:none]")}>
      <ToggleGroup type="single" size="sm" value={String(current)} onValueChange={(v) => { if (v) onSelect(Number(v)) }}
        aria-label="분기" className={cn(compact ? "flex-nowrap" : "flex-wrap justify-end")}>
        {shown.map((q) => (
          <ToggleGroupItem key={q.transcript_id} value={String(q.transcript_id)} className={cn("tabular-nums", compact ? "h-7 shrink-0 px-2.5 text-[12.5px]" : "h-[30px] px-3 text-[13px]")}
            title={`${quarterLabel(q.cy, q.fiscal_year, q.fiscal_period)}${q.call_date ? ` · ${q.call_date}` : ""}`}>
            {fyLabel(q)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  )
}

/* ---------- 폰 콜 상세 (시안 Mobile-Call) — 기업 바꾸기 · 분기 칩 · 한 줄 요지 · 발표 전후 주가 · 발표 전 쟁점 · 컨콜 핵심 · 분기별 첫 거래일 반응 ---------- */
function MobileCallDetail({ transcriptId, onSelect, rail }: { transcriptId: number; onSelect: (id: number) => void; rail: (onPick: (id: number) => void) => ReactNode }) {
  const { data, isLoading, isError, refetch } = useQuery(detailQuery(transcriptId))
  const chain = useChain(transcriptId)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [more, setMore] = useState(false)

  if (isLoading) return <div className="flex flex-col gap-3.5"><Skeleton className="h-16 w-full rounded-card" /><Skeleton className="h-48 w-full rounded-card" /></div>
  if (isError || !data) return <Card><CardContent className="py-10"><ErrorState onRetry={() => refetch()} /></CardContent></Card>

  const c = chain.data
  const h = c ? currentHistory(c, transcriptId) : undefined
  const grades = c?.reaction_meta?.grades ?? []
  const order = { high: 0, mid: 1, low: 2 } as const
  const topIssues = [...grades].sort((a, b) => order[a.weight ?? "low"] - order[b.weight ?? "low"]).slice(0, 2)
  const callPoints = [...(c?.reaction_meta?.call_points ?? []).slice(0, 2), ...(c?.reaction_meta?.react_points ?? []).slice(0, 1)]
  const clean = (t: string) => t.replace(/\s*\[\d+\]/g, "").trim()
  const box = "flex flex-col gap-2.5 p-3.5"
  const boxTitle = "text-[15px] font-semibold"

  return (
    <div className="flex flex-col gap-3.5">
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetTrigger asChild>
          <Button variant="outline" className="h-auto w-full justify-start gap-2.5 rounded-card bg-card px-3.5 py-3 text-left font-normal">
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate text-base font-semibold">{data.company_name} <span className="font-mono text-[12.5px] font-normal text-ink-3">{data.ticker}</span></span>
              <span className="truncate text-xs text-ink-3">{[c?.sector_name, quarterLabel(data.cy, data.fiscal_year, data.fiscal_period), data.call_date && `${mmdd(data.call_date)} 발표`].filter(Boolean).join(" · ")}</span>
            </span>
            <span className="ml-auto shrink-0 text-[12.5px] text-ink-2">기업 바꾸기 ▾</span>
          </Button>
        </SheetTrigger>
        <SheetContent side="bottom" className="max-h-[85vh] overflow-y-auto p-3">
          <SheetHeader className="p-0"><SheetTitle>기업 고르기</SheetTitle></SheetHeader>
          {rail((id) => { setSheetOpen(false); onSelect(id) })}
        </SheetContent>
      </Sheet>
      <QuarterTabs ticker={data.ticker} current={transcriptId} onSelect={onSelect} compact />
      {c?.reaction_meta?.headline && <p className="text-[15px] font-semibold leading-[1.55]">{c.reaction_meta.headline}</p>}

      <QueryState query={chain} isEmpty={() => false} loading={<Skeleton className="h-48 w-full rounded-card" />}>
        {(cd) => <div className="flex flex-col gap-3.5">
          <Card className={box}>
            <h2 className={cn(boxTitle, "flex items-center gap-1.5")}>발표 전후 주가
              <InfoTip label="발표 전후 주가 설명">{cd.etf} 비교 · 발표 전 마지막 거래일 = 0</InfoTip></h2>
            <CallWindowChart chain={cd} compact />
            {(h?.d1 != null || (cd.pt_after?.n ?? 0) > 0) && (
              <span className="text-[12.5px]">
                {h?.d1 != null && <>첫 거래일 {cd.etf} 대비 <span className={cn("font-mono tabular-nums", h.d1 > 0 ? "text-up-ink" : h.d1 < 0 ? "text-down-ink" : "")}>{formatPp(h.d1)}</span></>}
                {h?.d1 != null && (cd.pt_after?.n ?? 0) > 0 && " · "}
                {(cd.pt_after?.n ?? 0) > 0 && <>발표 후 7일 목표가 {cd.pt_after!.down >= cd.pt_after!.up ? `내림 ${cd.pt_after!.down}` : `올림 ${cd.pt_after!.up}`}건</>}
              </span>
            )}
          </Card>
          {topIssues.length > 0 && (
            <Card className={box}>
              <h2 className={boxTitle}>발표 전 쟁점</h2>
              {topIssues.map((g) => (
                <div key={g.issue} className="flex flex-col gap-1.5 text-[13px] leading-[1.55]">
                  <span><b className="font-semibold">{g.issue}</b> {g.weight && <Badge variant={g.weight === "high" ? "warn" : "outline"}>{WEIGHT[g.weight]}</Badge>}</span>
                  {g.outcome && <span className="text-ink-2">{g.outcome}</span>}
                </div>
              ))}
            </Card>
          )}
        </div>}
      </QueryState>

      <Card className={box}>
        <h2 className={boxTitle}>컨콜 핵심</h2>
        {callPoints.length > 0
          ? <ul className="flex list-disc flex-col gap-1 pl-4 text-[13px] leading-[1.6] marker:text-ink-3">{callPoints.map((t, i) => <li key={i}>{clean(t)}</li>)}</ul>
          : <p className="text-caption text-muted-foreground">아래 핵심 정리를 펼쳐 보세요.</p>}
        <Collapsible open={more} onOpenChange={setMore}>
          <CollapsibleTrigger className="text-left text-[13px] font-medium text-ink">{more ? "접기" : "핵심 정리 전체 · 원문 ›"}</CollapsibleTrigger>
          <CollapsibleContent className="pt-2"><DetailFolds data={data} transcriptId={transcriptId} /></CollapsibleContent>
        </Collapsible>
      </Card>

      {c && c.history.length > 0 && (
        <Card className="flex flex-col p-3.5">
          <h2 className={cn(boxTitle, "pb-1.5")}>분기별 첫 거래일 반응</h2>
          {c.history.map((r) => (
            <div key={`${r.fiscal}-${r.event_date}`} className={cn("grid grid-cols-[70px_64px_1fr] gap-2 border-t border-line py-2 text-[12.5px]",
              r.transcript_id === transcriptId && "font-semibold")}>
              {r.transcript_id && r.transcript_id !== transcriptId
                ? <button type="button" className="text-left hover:underline" onClick={() => onSelect(r.transcript_id!)}>{fyShort(r.fiscal)}</button>
                : <span>{fyShort(r.fiscal)}</span>}
              <span className={cn("font-mono tabular-nums", r.d1 == null ? "text-ink-3" : r.d1 > 0 ? "text-up-ink" : r.d1 < 0 ? "text-down-ink" : "")}>{formatPp(r.d1, 1)}</span>
              <span className="text-ink-2">{r.follow ?? "-"}</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}

function TranscriptSkeleton() {
  return (
    <PageContainer>
      <Skeleton className="h-6 w-32" />
      <div className="surface-grid grid grid-cols-1 md:grid-cols-[240px_1fr]">
        <Skeleton className="h-96 w-full rounded-card" />
        <Skeleton className="h-96 w-full rounded-card" />
      </div>
    </PageContainer>
  )
}
