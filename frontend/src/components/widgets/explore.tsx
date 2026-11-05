import { Link } from "react-router-dom"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { useCallMomentum, useRecentCalls } from "@/hooks/useTranscripts"
import { formatNumber } from "@/utils/format"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"
import { TrendBody, useTrendMeta } from "./trend"

/* 탐색 섹션 본문 — 컨콜(새 모멘텀·최근 받은 컨콜). 캐시된 GET만, 머리 시각 = 원천 시각(마지막 판정 · 마지막 수집). */

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
                <Link to={`/follow/transcripts?view=season&pick=${c.ticker}#momentum`} className="font-medium hover:underline">{c.ticker}</Link>
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
// 곧 발표는 위 실적 시즌 블록 하나로 — 이 줄은 최근 받은 컨콜만(D-303)
function CallsBody({ h }: WidgetBodyProps) {
  const q = useRecentCalls(7)
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  // 받은 순이 아니라 발표일 순 — 늦게 받은 옛 분기 콜이 '최근'으로 보이지 않게
  const rows = [...q.data].sort((a, b) => (b.call_date ?? "").localeCompare(a.call_date ?? "")).slice(0, h > 3 ? 10 : 2)
  return <div className="flex h-full flex-col gap-2 overflow-hidden">
    <p className="text-[11px] font-medium text-muted-foreground">지난 7일 {formatNumber(q.data.length)}건</p>
    {!q.data.length ? <p className="text-[13px] text-muted-foreground">지난 7일간 새로 받은 컨콜이 없어요. 매일 07:20에 수집합니다.</p> :
    <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {rows.map(c => (
        <li key={c.transcript_id} className="flex items-center gap-2 py-1.5 first:pt-0">
          <Link to={`/follow/transcripts?t=${c.transcript_id}`} className="font-medium hover:underline">{c.ticker}</Link>
          <span className="min-w-0 truncate text-muted-foreground">{c.cy ?? `FY${c.fiscal_year} ${c.fiscal_period}`}</span>
          <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">{c.call_date ? `${c.call_date.slice(5)} 발표` : "-"}</span>
        </li>
      ))}
    </ul>}
  </div>
}

/** 탐색 위젯 — 이 영역 단계에서 채운다 (docs/specs/home-widgets.md §2 계약). registry.tsx가 이 배열을 그대로 펼친다 */
export const EXPLORE_WIDGETS: WidgetDef[] = [
  { id: "explore.trend", title: "가파른 추세", description: "60거래일 +30% 이상을 고르게 오르며 정배열·ADX 25+인 국내 종목 · 52주 신고가·매물대 돌파 후 지지",
    detailPath: "/discover", useMeta: useTrendMeta, Body: TrendBody },
  { id: "explore.momentum", title: "새 모멘텀 후보", description: "이번 시즌 콜에서 새로 생기거나 빨라진 성장 동인 · 미국 기업. 실적 시즌 개요의 '새 모멘텀 후보'와 같은 판정입니다",
    detailPath: "/follow/transcripts?view=season#momentum", useMeta: useMomentumMeta, Body: MomentumBody },
  { id: "explore.calls", title: "최근 받은 컨콜", description: "지난 7일 받은 컨콜 · 발표일 순",
    detailPath: "/follow/transcripts", useMeta: useCallsMeta, Body: CallsBody },
]
