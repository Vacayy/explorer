import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { TradeFlagBadge } from "@/components/follow/tradeFormat"
import { pinMine, useActions, useRights } from "@/hooks/useActions"
import { byWidening, useCreditTable } from "@/hooks/useCredit"
import { useFollowedPeopleWeek } from "@/hooks/usePeople"
import { useTradeHighlights } from "@/hooks/useTrade"
import { cn } from "@/lib/utils"
import { formatBp, formatKstDateTime, formatNumber, formatPercent, formatRatio } from "@/utils/format"
import { kstToday, upcomingRightsEvents } from "./rightsCalendar"
import type { WidgetBodyProps, WidgetMeta } from "./types"

/**
 * 탐색 위젯 — 수출입·회사채·인물·기업활동 (P6b, docs/specs/home-widgets.md §2).
 * 모두 저장분 GET만 읽는다(LLM·외부 호출 0). 머리 시각 = 원천 리듬:
 * 수출입 = 통계월, 회사채 = 시세 기준일(T-1), 인물 = 가장 최근 언급 문서 게시 시각, 기업활동 = 마지막 DART 스캔 성공 시각.
 */

const tone = (v: number | null | undefined) => v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-up" : "text-down"
const hoursSince = (iso: string) => (Date.now() - new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z").getTime()) / 3_600_000
const monthsBetween = (ym: string, today: string) => (+today.slice(0, 4) - +ym.slice(0, 4)) * 12 + (+today.slice(5, 7) - +ym.slice(5, 7))
const mmdd = (yyyymmdd: string) => `${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`

/* ── Trade Pulse ── */
export function useTradeMeta(): WidgetMeta {
  const q = useTradeHighlights()
  const p = q.data?.period ?? null
  // 관세청은 매월 15일경 전월을 낸다 — 두 달 넘게 묵으면 수집이 멈춘 것
  return { asOf: p ? `${p} 통계` : null, stale: !!p && monthsBetween(p, kstToday()) > 2 }
}
export function TradeBody({ h }: WidgetBodyProps) {
  const q = useTradeHighlights()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.period) return <WidgetState empty emptyText="수출입 통계가 아직 없어요. 매일 09:20에 새 통계월을 확인합니다." />
  const rows = [...d.surge, ...d.plunge].sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0))
  const top = rows[0]
  if (!top) return <WidgetState empty emptyText={`${d.period}에는 급등·급감 판정 품목이 없어요.`} />
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={<span className={tone(top.yoy)}>{formatPercent(top.yoy == null ? null : top.yoy * 100)}</span>}
      aside={<span className="truncate text-sm text-muted-foreground">{top.item_name} · 기여 {formatRatio((top.contribution ?? 0) * 100)}</span>} />
    <p className="text-[13px] text-muted-foreground">전년 동월 대비 · 급등 <span className="text-up">{d.groups.reduce((n, g) => n + g.surge, 0)}</span> · 급감 <span className="text-down">{d.groups.reduce((n, g) => n + g.plunge, 0)}</span></p>
    {h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rows.slice(1, h > 3 ? 5 : 3).map(r => (
        <li key={r.hs_code} className="flex items-center gap-2 py-1.5">
          <Link to={`/follow/trade?hs=${encodeURIComponent(r.hs_code)}`} className="min-w-0 truncate hover:underline">{r.item_name}</Link>
          <TradeFlagBadge flag={r.flag} reason={r.reason} contribution={r.contribution} />
          <span className={cn("ml-auto shrink-0 tabular-nums", tone(r.yoy))}>{formatPercent(r.yoy == null ? null : r.yoy * 100)}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 신용 긴장 Top ── */
export function useCreditMeta(): WidgetMeta {
  const q = useCreditTable()
  const a = q.data?.as_of ?? null
  return { asOf: a, stale: !!q.data && (!q.data.configured || (!!a && hoursSince(`${a}T00:00:00Z`) > 4 * 24)) }
}
export function CreditBody({ h }: WidgetBodyProps) {
  const q = useCreditTable()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.configured) return <WidgetState empty emptyText="채권 데이터 원천이 설정되지 않았어요(로컬 어댑터 필요)." />
  const rows = d.rows.filter(r => r.chg_1m != null).sort(byWidening)
  const top = rows[0]
  if (!top) return <WidgetState empty emptyText="1개월 변화를 계산할 시세가 아직 없어요. 매일 07:30에 받습니다." />
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={<span className={tone(top.chg_1m)}>{formatBp(top.chg_1m, true)}bp</span>}
      aside={<span className="truncate text-sm text-muted-foreground">{top.name} · {formatBp(top.spread_bp)}bp{top.hy && " · HY"}</span>} />
    <p className="text-[13px] text-muted-foreground">1개월 새 스프레드가 가장 벌어진 곳 · AI 설비투자 관련 미국 기업 {d.rows.length}곳</p>
    {h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rows.slice(1, h > 3 ? 5 : 3).map(r => (
        <li key={r.ticker} className="flex items-center gap-2 py-1.5">
          <Link to={`/follow/credit?credit=${r.ticker}`} className="min-w-0 truncate hover:underline">{r.name} <span className="text-muted-foreground">{r.ticker}</span></Link>
          {r.hy && <Badge variant="outline" className="h-4 shrink-0 border-up/40 px-1 text-[10px] text-up">HY</Badge>}
          <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{formatBp(r.spread_bp)}bp</span>
          <span className={cn("w-14 shrink-0 text-right tabular-nums", tone(r.chg_1m))}>{formatBp(r.chg_1m, true)}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 팔로우 인물 이번 주 ── */
export function usePeopleMeta(): WidgetMeta {
  const q = useFollowedPeopleWeek()
  const a = q.data?.as_of ?? null
  return { asOf: a ? formatKstDateTime(a) : null, stale: !!a && hoursSince(a) > 36 }
}
export function PeopleBody({ h }: WidgetBodyProps) {
  const q = useFollowedPeopleWeek()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.items.length) return <WidgetState empty emptyText="팔로우한 인물이 없어요. 탐색 › 인물에서 팔로우하면 여기서 주간 언급을 봅니다." />
  const top = d.items[0]
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`${formatNumber(top.mentions_7d)}건`}
      aside={<span className="truncate text-sm text-muted-foreground">{top.name} <span className={tone(top.delta_7d)}>({top.delta_7d > 0 ? "+" : ""}{formatNumber(top.delta_7d)})</span></span>} />
    <p className={cn("text-[13px] text-muted-foreground", h <= 2 ? "line-clamp-1" : "line-clamp-2")}>
      {top.last_doc_id ? <Link to={`/doc/${top.last_doc_id}`} className="hover:underline">{top.last_doc_title}</Link> : "최근 7일 언급 · 직전 7일 대비"}
    </p>
    {h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {d.items.slice(1, h > 3 ? 5 : 3).map(p => (
        <li key={p.entity_id} className="flex items-center gap-2 py-1.5">
          <Link to={`/person?name=${encodeURIComponent(p.name)}`} className="shrink-0 font-medium hover:underline">{p.name}</Link>
          <span className="min-w-0 truncate text-[11px] text-muted-foreground">{p.top_stocks.join(" · ")}</span>
          <span className="ml-auto shrink-0 tabular-nums">{formatNumber(p.mentions_7d)}</span>
          <span className={cn("w-10 shrink-0 text-right tabular-nums", tone(p.delta_7d))}>{p.delta_7d > 0 ? "+" : ""}{formatNumber(p.delta_7d)}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 오늘 기업활동 (원공시만, 내 종목 먼저) ── */
export function useActionsMeta(): WidgetMeta {
  const q = useActions({ days: 7, kind: "original" })
  const a = q.data?.as_of ?? null
  // 30분 주기 스캔 — 3시간 넘게 성공이 없으면 고장(노트북 수면 포함)
  return { asOf: a ? formatKstDateTime(a) : null, stale: !!q.data && (!a || hoursSince(a) > 3) }
}
export function ActionsBody({ h }: WidgetBodyProps) {
  const q = useActions({ days: 7, kind: "original" })
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.items.length) return <WidgetState empty emptyText="최근 7일 원공시가 없어요(시총 5,000억+ 유·무상증자·합병·분할·공개매수·감자)." />
  const today = kstToday().replace(/-/g, "")
  const nToday = d.items.filter(a => a.rcept_dt === today).length
  const mine = d.items.filter(a => a.my_group).length
  const rows = pinMine(d.items).slice(0, h > 3 ? 5 : h > 2 ? 3 : 0)
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={`오늘 ${formatNumber(nToday)}건`}
      aside={<span className="text-sm text-muted-foreground">7일 {formatNumber(d.items.length)}건{mine > 0 && <> · <span className="text-up">내 종목 {mine}</span></>}</span>} />
    {rows.length > 0 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rows.map(a => (
        <li key={a.id} className="flex items-center gap-2 py-1.5">
          <Badge variant="secondary" className={cn("h-4 shrink-0 px-1 text-[10px]", a.action_type === "유상증자" && "bg-down/10 text-down", a.action_type === "무상증자" && "bg-up/10 text-up")}>{a.action_type}</Badge>
          {a.stock_code ? <Link to={`/analyze/${a.stock_code}/summary`} className="min-w-0 truncate hover:underline">{a.corp_name}</Link> : <span className="min-w-0 truncate">{a.corp_name}</span>}
          {a.my_group && <Badge variant="outline" className="h-4 shrink-0 border-up/40 px-1 text-[10px] text-up">{a.my_group}</Badge>}
          <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{mmdd(a.rcept_dt)}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── 유무증 D-day ── */
export function useRightsMeta(): WidgetMeta {
  const q = useRights()
  const a = q.data?.as_of ?? null
  return { asOf: a ? formatKstDateTime(a) : null, stale: !!q.data && (!a || hoursSince(a) > 3) }
}
export function RightsBody({ h }: WidgetBodyProps) {
  const q = useRights()
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const events = upcomingRightsEvents(d.items, kstToday(), 7)
  if (!events.length) return <WidgetState empty emptyText="7일 안에 권리락·청약·신주 상장 일정이 없어요." />
  const next = events[0]
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={next.dday === 0 ? "D-day" : `D-${next.dday}`}
      aside={<span className="truncate text-sm text-muted-foreground">{next.row.corp_name} {next.label}</span>} />
    <p className="text-[13px] text-muted-foreground">7일 안 일정 {formatNumber(events.length)}건 · 유·무상증자 결정 공시 기준</p>
    {h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {events.slice(1, h > 3 ? 5 : 3).map(e => (
        <li key={`${e.row.rcp_no}-${e.label}`} className="flex items-center gap-2 py-1.5">
          <span className="w-10 shrink-0 tabular-nums text-muted-foreground">{e.dday === 0 ? "D-day" : `D-${e.dday}`}</span>
          {e.row.stock_code ? <Link to={`/analyze/${e.row.stock_code}/summary`} className="min-w-0 truncate hover:underline">{e.row.corp_name}</Link> : <span className="min-w-0 truncate">{e.row.corp_name}</span>}
          {e.row.my_group && <Badge variant="outline" className="h-4 shrink-0 border-up/40 px-1 text-[10px] text-up">{e.row.my_group}</Badge>}
          <span className="ml-auto shrink-0 text-muted-foreground">{e.label}</span>
        </li>
      ))}
    </ul>}
  </div>
}
