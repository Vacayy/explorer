import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { SIGNAL_LABEL, signalEntityPath } from "@/components/shared/SignalCard"
import { useSignalsSummary } from "@/hooks/useSpineSignals"
import { useCallMomentum, useRecentCalls } from "@/hooks/useTranscripts"
import { quadrantOf, useSectorMap } from "@/hooks/useSectorMap"
import { cn } from "@/lib/utils"
import { SparkLine } from "@/components/shared/Spark"
import { useTrendLeaders } from "@/hooks/useTrendLeaders"
import { formatLevel, formatNumber, formatPercent } from "@/utils/format"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"
import {
  ActionsBody, CreditBody, PeopleBody, RightsBody, TradeBody,
  useActionsMeta, useCreditMeta, usePeopleMeta, useRightsMeta, useTradeMeta,
} from "./exploreFollow"

/* ───────────────────────── P6a 탐색: 신호 · 컨콜 · 산업·섹터 ─────────────────────────
 * docs/specs/home-widgets.md §2 계약 — 캐시된 GET만(signals/summary · transcript/momentum · transcript/recent · sector-map),
 * 머리 시각 = 원천 시각(신호 최신일 · 마지막 판정 · 마지막 수집 · 시세 기준일). */

/** 원천 날짜가 기준보다 n일 넘게 묵었나 — 매일 도는 원천의 '멈춤' 판정 */
const olderThan = (iso: string | null | undefined, days: number) =>
  !!iso && Date.now() - new Date(iso.slice(0, 10) + "T00:00:00").getTime() > (days + 1) * 86_400_000
/** SQLite UTC("2026-10-13 23:44:12") → KST "10/14 08:44" */
const kstStamp = (utc: string | null | undefined) => {
  if (!utc) return null
  const d = new Date(utc.includes("T") ? utc : utc.replace(" ", "T") + "Z")
  if (Number.isNaN(d.getTime())) return null
  const p = Object.fromEntries(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })
    .formatToParts(d).map(x => [x.type, x.value]))
  return `${p.month}/${p.day} ${p.hour}:${p.minute}`
}

/* ── 오늘의 신호 ── */
function useSignalsMeta(): WidgetMeta {
  const q = useSignalsSummary(7)
  return { asOf: q.data?.as_of ?? null, stale: olderThan(q.data?.as_of, 1) }
}
function SignalsBody({ h }: WidgetBodyProps) {
  const q = useSignalsSummary(7)
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.types.length) return <WidgetState empty emptyText="아직 계산된 신호가 없어요. 매일 아침 계산합니다." />
  const today = d.types.filter(t => t.latest_date === d.as_of)
  const total = today.reduce((n, t) => n + t.count_latest, 0)
  const rows = d.types.slice(0, h > 3 ? 6 : 3)
  return <div className="flex h-full flex-col gap-2">
    {olderThan(d.as_of, 1) && <p className="text-xs text-chart-warning">신호 계산이 {d.as_of} 이후 멈춰 있어요.</p>}
    <WidgetHero value={`${formatNumber(total)}건`} aside={<span className="text-sm text-muted-foreground">{d.as_of} · {today.length}개 유형</span>} />
    <ul className="min-h-0 space-y-1.5 overflow-hidden text-[13px]">
      {rows.map(t => (
        <li key={t.type} className="flex min-w-0 items-center gap-2">
          <Link to={`/explore?list=${t.type}`} className="w-24 shrink-0 truncate hover:underline">{SIGNAL_LABEL[t.type] ?? t.type}</Link>
          <span className={cn("w-10 shrink-0 text-right tabular-nums", t.latest_date !== d.as_of && "text-muted-foreground")}
            title={t.latest_date !== d.as_of ? `${t.latest_date} 기준` : undefined}>{formatNumber(t.count_latest)}</span>
          <span className="flex min-w-0 flex-1 gap-1 overflow-hidden">
            {t.top.slice(0, h > 3 ? 2 : 1).map(x => (
              <Badge key={x.entity_id} variant="outline" className="max-w-full truncate font-normal" asChild>
                <Link to={signalEntityPath(x)}>{x.name}</Link>
              </Badge>
            ))}
          </span>
        </li>
      ))}
    </ul>
  </div>
}

/* ── 이번 시즌 실적 모멘텀 ── */
function useMomentumMeta(): WidgetMeta {
  const q = useCallMomentum()
  return { asOf: kstStamp(q.data?.as_of), stale: !!q.data && (olderThan(q.data.as_of, 2) || !q.data.sec_configured) }
}
function MomentumBody({ h }: WidgetBodyProps) {
  const q = useCallMomentum()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const top = [...d.candidates].sort((a, b) => b.score - a.score).slice(0, h > 3 ? 3 : 1)
  return <div className="flex h-full flex-col gap-2">
    {!d.sec_configured && <p className="text-xs text-chart-warning">SEC 보도자료 수집이 멈춰 있어요(SEC_USER_AGENT 미설정).</p>}
    {d.sec_configured && olderThan(d.as_of, 2) && <p className="text-xs text-chart-warning">매일 판정이 {kstStamp(d.as_of)} 이후 돌지 않았어요.</p>}
    <WidgetHero value={`${formatNumber(d.candidates.length)}건`}
      aside={<span className="text-sm text-muted-foreground">{d.season.label} · 발표 분석 {formatNumber(d.season.reported)}개사</span>} />
    {!top.length
      ? <p className="text-[13px] text-muted-foreground">{d.season.reported ? "이번 시즌 새 모멘텀으로 판정된 곳이 아직 없어요." : "이번 시즌 발표가 아직 분석되지 않았어요."}</p>
      : <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
          {top.map(c => {
            const lead = c.drivers.find(x => x.status === "new") ?? c.drivers.find(x => x.status === "accelerating")
            return <li key={`${c.ticker}-${c.event_date}`} className="space-y-0.5 py-1.5 first:pt-0">
              <div className="flex items-baseline gap-2">
                <Link to={`/us/${c.ticker}`} className="font-medium hover:underline">{c.ticker}</Link>
                <span className="min-w-0 truncate text-muted-foreground">{c.name}</span>
                <span className="ml-auto shrink-0 tabular-nums">점수 {formatNumber(c.score)}</span>
              </div>
              {lead && <p className="truncate text-xs text-muted-foreground">{lead.name}{lead.magnitude ? ` · ${lead.magnitude}` : ""}</p>}
            </li>
          })}
        </ul>}
  </div>
}

/* ── 최근 받은 컨콜 ── */
function useCallsMeta(): WidgetMeta {
  const q = useRecentCalls(7)
  const latest = (q.data ?? []).reduce<string | null>((m, c) => (c.fetched_at && (!m || c.fetched_at > m) ? c.fetched_at : m), null)
  return { asOf: kstStamp(latest) }
}
function CallsBody({ h }: WidgetBodyProps) {
  const q = useRecentCalls(7)
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!q.data.length) return <WidgetState empty emptyText="지난 7일간 새로 받은 컨콜이 없어요. 매일 07:20에 수집합니다." />
  // 받은 순이 아니라 발표일 순 — 늦게 받은 옛 분기 콜이 '최근'으로 보이지 않게
  const rows = [...q.data].sort((a, b) => (b.call_date ?? "").localeCompare(a.call_date ?? "")).slice(0, h > 3 ? 5 : h === 3 ? 3 : 1)
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${formatNumber(q.data.length)}건`} aside={<span className="text-sm text-muted-foreground">지난 7일 수집</span>} />
    <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rows.map(c => (
        <li key={c.transcript_id} className="flex items-center gap-2 py-1.5 first:pt-0">
          <Link to={`/follow/transcripts?t=${c.transcript_id}`} className="font-medium hover:underline">{c.ticker}</Link>
          <span className="min-w-0 truncate text-muted-foreground">{c.cy ?? `FY${c.fiscal_year} ${c.fiscal_period}`}</span>
          <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">{c.call_date ? `${c.call_date.slice(5)} 발표` : "-"}</span>
        </li>
      ))}
    </ul>
  </div>
}

/* ── 섹터 사분면 이동 (1주 전 → 지금) ── */
function useSectorMeta(): WidgetMeta {
  const q = useSectorMap()
  return { asOf: q.data?.as_of ?? null, stale: olderThan(q.data?.as_of, 3) }
}
function SectorShiftBody({ h }: WidgetBodyProps) {
  const q = useSectorMap()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.groups.length) return <WidgetState empty emptyText="주가·섹터 데이터가 쌓이면 나타나요." />
  const moves = d.groups.flatMap(g => {
    const prev = g.trail.find(t => t.weeks_ago === 1)
    const from = prev ? quadrantOf(prev.rs_long, prev.rs_short) : null
    const to = quadrantOf(g.rs_long, g.rs_short)
    return from && to && from !== to ? [{ g, from, to, dShort: (g.rs_short ?? 0) - (prev?.rs_short ?? 0) }] : []
  }).sort((a, b) => Math.abs(b.dShort) - Math.abs(a.dShort))
  const rows = moves.slice(0, h > 3 ? 5 : h === 3 ? 3 : 1)
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${formatNumber(moves.length)}개 섹터`} aside={<span className="text-sm text-muted-foreground">1주 전과 사분면이 바뀜 · 18 대분류</span>} />
    {!rows.length
      ? <p className="text-[13px] text-muted-foreground">이번 주는 사분면을 옮긴 섹터가 없어요.</p>
      : <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
          {rows.map(({ g, from, to, dShort }) => (
            <li key={g.name} className="flex items-center gap-2 py-1.5 first:pt-0">
              <Link to={`/map?group=${encodeURIComponent(g.name)}`} className="min-w-0 truncate font-medium hover:underline">{g.name}</Link>
              <span className="ml-auto shrink-0 text-muted-foreground">{from} → <span className="text-foreground">{to}</span></span>
              <span className={cn("w-12 shrink-0 text-right text-xs tabular-nums", dShort >= 0 ? "text-up" : "text-down")} title="단기 RS 변화(1주)">
                {dShort >= 0 ? "+" : ""}{formatNumber(dShort)}
              </span>
            </li>
          ))}
        </ul>}
  </div>
}

/** 탐색 위젯 — 이 영역 단계에서 채운다 (docs/specs/home-widgets.md §2 계약). registry.tsx가 이 배열을 그대로 펼친다 */
/* ── 가파른 추세 — 빠르게, 그러면서 고르게 오른 종목 (pipeline/trend_leaders) ── */
function useTrendMeta(): WidgetMeta {
  const q = useTrendLeaders()
  return { asOf: q.data?.as_of ?? null, stale: olderThan(q.data?.as_of, 4) }
}
function TrendBody({ w, h }: WidgetBodyProps) {
  const q = useTrendLeaders()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.items.length) return <WidgetState empty emptyText={`조건을 모두 통과한 종목이 없어요. (${d.criteria})`} />
  const wide = w >= 6
  const fresh = d.items.filter(i => i.new).length
  return <div className="flex h-full flex-col gap-2">
    <p className="text-[12px] text-muted-foreground" title={d.criteria}>
      시총 3,000억+ {formatNumber(d.universe)}종목 중 <span className="font-medium text-foreground">{formatNumber(d.passed)}</span>개
      {fresh > 0 && <> · 5거래일 새 진입 {formatNumber(fresh)}</>}
    </p>
    <div className={cn("grid items-center gap-x-3 border-b pb-1 text-[11px] text-muted-foreground", wide ? "grid-cols-[minmax(0,1fr)_64px_52px_40px_40px_48px]" : "grid-cols-[minmax(0,1fr)_56px_52px]")}>
      <span>종목</span><span>60일</span><span className="text-right">수익률</span>
      {wide && <><span className="text-right" title="60거래일 log 가격 회귀의 R² — 1에 가까울수록 고르게 올랐다">고름</span>
        <span className="text-right" title="ADX(14) — 추세 강도">ADX</span>
        <span className="text-right" title="20일 이동평균 대비 — 클수록 단기 과열">이격</span></>}
    </div>
    <ul className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2 text-[13px]">
      {d.items.slice(0, h > 3 ? d.items.length : 4).map(t => (
        <li key={t.stock_code}>
          <Link to={`/analyze/${t.stock_code}/summary?scan=1`} title={`${t.name} 기술적 분석 열기`}
            className={cn("grid items-center gap-x-3 rounded-sm py-1 hover:bg-muted/50", wide ? "grid-cols-[minmax(0,1fr)_64px_52px_40px_40px_48px]" : "grid-cols-[minmax(0,1fr)_56px_52px]")}>
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-medium">{t.name}</span>
              {t.new && <Badge variant="outline" className="shrink-0 px-1 text-[10px] text-primary">신규</Badge>}
              {wide && t.sector && <span className="truncate text-[11px] text-muted-foreground">{t.sector}</span>}
            </span>
            <SparkLine data={t.spark} height={18} />
            <span className="text-right tabular-nums text-up">{formatPercent(t.ret_60)}</span>
            {wide && <><span className="text-right tabular-nums text-muted-foreground">{formatLevel(t.r2)}</span>
              <span className="text-right tabular-nums text-muted-foreground">{formatNumber(Math.round(t.adx))}</span>
              <span className={cn("text-right tabular-nums", t.gap_ma20 >= 15 ? "text-chart-warning" : "text-muted-foreground")}>{formatPercent(t.gap_ma20)}</span></>}
          </Link>
        </li>
      ))}
    </ul>
  </div>
}

export const EXPLORE_WIDGETS: WidgetDef[] = [
  { id: "explore.trend", title: "가파른 추세", description: "60거래일 +30% 이상을 고르게 오르며 정배열·ADX 25+인 국내 종목", section: "explore", group: "기술적 분석",
    size: { w: 6, h: 5, minW: 3, minH: 2 }, detailPath: "/discover", useMeta: useTrendMeta, Body: TrendBody },
  // P6a — 신호 · 컨콜 · 산업·섹터
  { id: "explore.signals", title: "오늘의 신호", description: "유형별 오늘 건수 · 상위 종목", section: "explore", group: "신호",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/explore", useMeta: useSignalsMeta, Body: SignalsBody },
  { id: "explore.momentum", title: "이번 시즌 실적 모멘텀", description: "새로 생기거나 빨라진 성장 동인 · 미국 기업", section: "explore", group: "컨콜",
    size: { w: 4, h: 4, minW: 3, minH: 2 }, detailPath: "/follow/transcripts?view=momentum", useMeta: useMomentumMeta, Body: MomentumBody },
  { id: "explore.calls", title: "최근 받은 컨콜", description: "지난 7일 수집 · 발표일 순", section: "explore", group: "컨콜",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/follow/transcripts", useMeta: useCallsMeta, Body: CallsBody },
  { id: "explore.sectorShift", title: "섹터 사분면 이동", description: "1주 전과 RS 사분면이 바뀐 대분류", section: "explore", group: "산업·섹터",
    size: { w: 4, h: 4, minW: 3, minH: 2 }, detailPath: "/map", useMeta: useSectorMeta, Body: SectorShiftBody },
  // P6a 끝
  // P6b — 수출입·회사채·인물·기업활동 (본문은 exploreFollow.tsx)
  { id: "explore.trade", title: "Trade Pulse", description: "이번 통계월 급등·급감 품목 · 기여도 순", section: "explore", group: "수출입",
    size: { w: 4, h: 4, minW: 3, minH: 2 }, detailPath: "/follow/trade", useMeta: useTradeMeta, Body: TradeBody },
  { id: "explore.credit", title: "신용 긴장 Top", description: "1개월 새 회사채 스프레드가 가장 벌어진 곳", section: "explore", group: "회사채",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/follow/credit", useMeta: useCreditMeta, Body: CreditBody },
  { id: "explore.people", title: "팔로우 인물 이번 주", description: "7일 언급 · 지난주 대비 · 최신 문서", section: "explore", group: "인물",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/people", useMeta: usePeopleMeta, Body: PeopleBody },
  { id: "explore.actions", title: "오늘 기업활동", description: "원공시만 · 내 종목 먼저 · 최근 7일", section: "explore", group: "기업활동",
    size: { w: 4, h: 4, minW: 3, minH: 2 }, detailPath: "/actions", useMeta: useActionsMeta, Body: ActionsBody },
  { id: "explore.rights", title: "유무증 D-day", description: "7일 안 권리락·청약·신주 상장", section: "explore", group: "기업활동",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: "/actions?view=pro", useMeta: useRightsMeta, Body: RightsBody },
]
