import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError } from "@/components/home/blockState"
import { Pp, VerdictBadge, mmdd } from "@/components/follow/season/seasonUi"
import { useSeason } from "@/hooks/useTranscripts"
import { daysBetween, groupByDate, localToday, seasonPhase, type SeasonPhase } from "@/lib/seasonPhase"
import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/format"
import type { SeasonItem, SeasonOverview, SeasonWindow } from "@/types"

const SEASON = "/follow/transcripts?view=season"
const sectorPath = (key: string, season?: string) => `${SEASON}&sector=${encodeURIComponent(key)}${season ? `&season=${season}` : ""}`
const INFO = "팔로우 기업의 실적 발표를 시즌 단위로 봅니다. 첫 거래일 반응은 업종 ETF 대비 %p이고, 매일 07:20에 갱신합니다."

/** 오늘 — 개발 서버에서만 ?today=YYYY-MM-DD로 바꿔 시즌 사이 화면을 확인한다 */
export function useHomeToday(): string {
  const [params] = useSearchParams()
  const forced = import.meta.env.DEV ? params.get("today") : null
  return forced && /^\d{4}-\d{2}-\d{2}$/.test(forced) ? forced : localToday()
}

/**
 * 홈 › 미국 시장 — 실적 시즌 블록 (시안 Home-US, ia-redesign §4.3·§4.28). 결론과 입구만 둔다(차트·종목 표는 탐색 › 컨콜).
 * 시즌 중: 판정 줄 · 이번 시즌 시장이 따진 것(섹터 4줄) · 곧 발표 칩. 시즌 사이: 다음 시즌까지 D-n · 지난 시즌 정리 · 곧 발표 · 그 사이 볼 것.
 * 오류는 이 블록만(§4.28) — 브리핑·거래대금 블록은 따로 불러온다.
 */
export function UsSeasonBlock() {
  const today = useHomeToday()
  const q = useSeason()
  const d = q.data
  if (!d) return <Frame title="실적 시즌">
    {q.isError ? <BlockError message="실적 시즌 요약을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <SeasonSkeleton />}
  </Frame>
  if (!d.counts.followed) return <Frame title={d.season.label}>
    <div className="space-y-2 text-sm">
      <p className="text-muted-foreground">팔로우한 기업이 없습니다.</p>
      <Button asChild variant="outline" size="sm"><Link to="/follow/transcripts">기본 세트 팔로우</Link></Button>
    </div>
  </Frame>
  const phase = seasonPhase(today, d.windows)
  if (phase.state === "between") return <BetweenSeasons base={d} phase={phase} today={today} />
  return phase.current.key === d.season.key
    ? <InSeason d={d} today={today} />
    : <OtherSeason seasonKey={phase.current.key} today={today} />
}

/** 시즌 판정이 서버의 '이번 시즌'(달력 분기)과 다를 때 — 그 시즌을 따로 불러온다 */
function OtherSeason({ seasonKey, today }: { seasonKey: string; today: string }) {
  const q = useSeason(seasonKey)
  if (!q.data) return <Frame title="실적 시즌">
    {q.isError ? <BlockError message="실적 시즌 요약을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <SeasonSkeleton />}
  </Frame>
  return <InSeason d={q.data} today={today} />
}

function Frame({ title, badge, link = { to: SEASON, label: "실적 시즌 전체" }, children }: { title: ReactNode; badge?: ReactNode; link?: { to: string; label: string }; children: ReactNode }) {
  return (
    <Card data-home-section="us.season" className="min-w-0 gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none">
      <BlockHead title={<span className="flex items-center gap-2">{title}{badge}</span>} info={INFO} link={link} />
      <div className="p-3 sm:p-4">{children}</div>
    </Card>
  )
}

function SeasonSkeleton() {
  return <div role="status" aria-label="데이터 불러오는 중" aria-busy="true" className="space-y-3">
    <div className="grid grid-cols-2 gap-px border md:grid-cols-5">{[0, 1, 2, 3, 4].map(i => <div key={i} className="space-y-2 p-3"><Skeleton className="h-3 w-16" /><Skeleton className="h-6 w-12" /></div>)}</div>
    <Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-11/12" /><Skeleton className="h-12 w-full" />
  </div>
}

function Stat({ label, value, of, cls, className }: { label: string; value: number; of?: number; cls?: string; className?: string }) {
  return <div className={cn("min-w-0 bg-card px-3 py-2.5", className)}>
    <p className="truncate text-[11px] text-muted-foreground">{label}</p>
    <p className="mt-1 font-mono text-lg tabular-nums"><span className={cls}>{formatNumber(value)}</span>
      {of != null && <span className="text-xs text-muted-foreground"> / {formatNumber(of)}</span>}</p>
  </div>
}

/** 판정 줄 — 발표 · 첫 거래일 업종보다 강함 · 하회에도 강세 · 상회에도 약세 · 첫 반응 뒤집힘 */
function Verdicts({ c, compact = false }: { c: SeasonOverview["counts"]; compact?: boolean }) {
  return <div className={cn("grid gap-px border bg-border", compact ? "grid-cols-2" : "grid-cols-2 md:grid-cols-5")}>
    <Stat label="발표" value={c.reported} of={c.followed} />
    <Stat label={compact ? "업종보다 강함" : "첫 거래일 업종보다 강함"} value={c.up} of={compact ? undefined : c.reported} cls="text-up-ink" />
    {!compact && <Stat label="컨센서스 하회에도 주가 강세" value={c.miss_up} of={c.miss} cls="text-up-ink" />}
    <Stat label={compact ? "상회에도 약세" : "컨센서스 상회에도 주가 약세"} value={c.beat_down} of={compact ? undefined : c.beat} cls="text-down-ink" />
    <Stat label="첫 반응이 뒤집힘" value={c.reversed} className={compact ? undefined : "max-md:col-span-2"} />
  </div>
}

function InSeason({ d, today }: { d: SeasonOverview; today: string }) {
  const pending = d.reported.filter(r => r.d1 == null).length
  const sectors = d.sectors.filter(s => s.one_line).slice(0, 4)
  const upcoming = d.upcoming.filter(u => u.event_date >= today)
  return <Frame title={d.season.label} badge={pending > 0 && <Badge variant="outline" className="h-5 border-chart-warning/50 px-1.5 text-[11px] font-normal text-chart-warning max-sm:hidden">반응 집계 중 {formatNumber(pending)}</Badge>}>
    <div className="space-y-4">
      <Verdicts c={d.counts} />

      <section aria-label="이번 시즌 시장이 따진 것">
        <h3 className="mb-1 text-xs font-semibold">이번 시즌 시장이 따진 것</h3>
        {!sectors.length ? <p className="py-2 text-sm text-muted-foreground">섹터 요약이 아직 없습니다. 반응 정리 {formatNumber(d.counts.reactions)}/{formatNumber(d.counts.reported)}</p>
          : <ul className="divide-y border-y">{sectors.map(s => (
            <li key={s.key}>
              <Link to={sectorPath(s.key)} className="grid gap-x-4 gap-y-1 px-1 py-3 transition-colors hover:bg-muted/50 sm:grid-cols-[9rem_minmax(0,1fr)_auto]">
                <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold sm:flex-col sm:items-start">{s.name}<VerdictBadge verdict={s.verdict} /></span>
                <span className="min-w-0 space-y-1">
                  <span className="line-clamp-2 block text-[13px] leading-relaxed">{s.one_line}</span>
                  <span className="flex flex-wrap gap-x-2 font-mono text-[11px]">{s.tickers.map(t => <span key={t.ticker}><span className="text-muted-foreground">{t.ticker}</span> <Pp v={t.d1} /></span>)}</span>
                </span>
                <span className="text-xs text-muted-foreground max-sm:hidden">섹터 상세 ›</span>
              </Link>
            </li>
          ))}</ul>}
        <Link to={SEASON} className="mt-2 inline-block text-xs text-muted-foreground hover:text-foreground">섹터 {formatNumber(d.sectors.length)}개 모두 보기 ›</Link>
      </section>

      {!!upcoming.length && <section aria-label="곧 발표">
        <h3 className="mb-2 text-xs font-semibold">곧 발표</h3>
        <div className="flex flex-wrap gap-1.5">{upcoming.map(u => <UpcomingChip key={`${u.ticker}-${u.event_date}`} u={u} today={today} />)}</div>
      </section>}
    </div>
  </Frame>
}

function UpcomingChip({ u, today }: { u: SeasonItem; today: string }) {
  const n = daysBetween(today, u.event_date)
  return <Badge asChild variant="outline" className="h-6 gap-1.5 rounded-full px-2 font-mono text-[11px] font-normal">
    <Link to={u.transcript_id ? `/follow/transcripts?t=${u.transcript_id}` : `/us/${u.ticker}`} title={`${u.name ?? u.ticker} · ${u.event_date}${u.confirmed ? "" : " (예상일)"}`}>
      <span className={n <= 1 ? "text-up-ink" : "text-muted-foreground"}>{n === 0 ? "오늘" : `D-${n}`}</span>
      <span className="font-semibold text-foreground">{u.ticker}</span>
      <span className="text-muted-foreground">{mmdd(u.event_date)}</span>
    </Link>
  </Badge>
}

/** 시즌 사이 빈 상태 (§4.28) — 판정 줄·섹터 줄 대신 다음 시즌까지 D-n · 지난 시즌 정리 · 곧 발표 · 그 사이 볼 것 */
function BetweenSeasons({ base, phase, today }: { base: SeasonOverview; phase: Extract<SeasonPhase, { state: "between" }>; today: string }) {
  const { next, last, daysToNext } = phase
  return <Frame title={next ? <span className="flex items-baseline gap-2">다음 실적 시즌까지 <span className="font-mono text-base">D-{formatNumber(daysToNext)}</span></span> : "실적 시즌 사이"}
    badge={next && <span className="text-xs font-normal text-muted-foreground max-sm:hidden">{next.label.replace(" 실적 시즌", " 시즌")} · {mmdd(next.first)} 첫 발표</span>}>
    <div data-season-state="between" className="grid gap-px border bg-border lg:grid-cols-3">
      <LastSeason base={base} last={last} />
      <NextUpcoming base={base} next={next} today={today} />
      <section aria-label="그 사이 볼 것" className="bg-card p-3">
        <h3 className="mb-2 text-xs font-semibold">그 사이 볼 것</h3>
        <ul className="divide-y text-[13px]">
          <li><a href="#us-briefing" className="flex justify-between gap-2 py-2 hover:underline">어젯밤 미국장 브리핑<span className="text-xs text-muted-foreground">아래에 펼쳐 둠</span></a></li>
          <li><Link to="/home/macro" className="flex justify-between gap-2 py-2 hover:underline">홈 › 매크로<span className="text-xs text-muted-foreground">추세·금리·온도 ›</span></Link></li>
          <li><Link to={last ? `${SEASON}&season=${last.key}` : SEASON} className="flex justify-between gap-2 py-2 hover:underline">지난 시즌 콜 다시 읽기<span className="text-xs text-muted-foreground">탐색 › 컨콜 ›</span></Link></li>
        </ul>
      </section>
    </div>
  </Frame>
}

function LastSeason({ base, last }: { base: SeasonOverview; last: SeasonWindow | null }) {
  // 지난 시즌이 서버의 '이번 시즌'이면 이미 받은 응답을 쓰고, 아니면 그 시즌을 따로 부른다(같은 키면 캐시 공유)
  const q = useSeason(last && last.key !== base.season.key ? last.key : null)
  const d = last && last.key === base.season.key ? base : q.data
  return <section aria-label="지난 시즌 정리" className="space-y-2 bg-card p-3">
    <h3 className="text-xs font-semibold">지난 시즌 정리{last && <span className="font-normal text-muted-foreground"> · {last.label.replace(" 실적 시즌", "")}</span>}</h3>
    {!last ? <p className="text-sm text-muted-foreground">지난 시즌 기록이 없습니다.</p>
      : !d ? (q.isError ? <BlockError message="지난 시즌 정리를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <Skeleton className="h-28 w-full" />)
      : <>
        <Verdicts c={d.counts} compact />
        <Link to={`${SEASON}&season=${last.key}`} className="inline-block text-xs hover:underline">시장이 따진 것 {formatNumber(d.sectors.filter(s => s.one_line).length)}개 섹터 다시 보기 ›</Link>
      </>}
  </section>
}

function NextUpcoming({ base, next, today }: { base: SeasonOverview; next: SeasonWindow | null; today: string }) {
  const q = useSeason(next && next.key !== base.season.key ? next.key : null)
  const d = next && next.key === base.season.key ? base : q.data
  const days = d ? groupByDate(d.upcoming.filter(u => u.event_date >= today)).slice(0, 6) : []
  return <section aria-label="곧 발표 · 팔로우 기업" className="bg-card p-3">
    <h3 className="mb-2 text-xs font-semibold">곧 발표 · 팔로우 기업</h3>
    {!next ? <p className="text-sm text-muted-foreground">다음 시즌 발표 일정이 아직 없습니다.</p>
      : !d ? (q.isError ? <BlockError message="발표 일정을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <Skeleton className="h-28 w-full" />)
      : !days.length ? <p className="text-sm text-muted-foreground">확인된 발표 일정이 없습니다.</p>
      : <ul className="divide-y text-[13px]">{days.map(g => (
        <li key={g.date} className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2 py-2">
          <span className="font-mono text-xs tabular-nums text-muted-foreground">{mmdd(g.date)}{g.estimated && <span className="block text-[10px]">예상일</span>}</span>
          <span className="min-w-0 truncate">{g.items.slice(0, 5).map(u => u.ticker).join(" · ")}{g.items.length > 5 && <span className="text-muted-foreground"> 외 {g.items.length - 5}</span>}</span>
        </li>
      ))}</ul>}
  </section>
}
