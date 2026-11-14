import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError } from "@/components/home/blockState"
import { VerdictBadge, mmdd } from "@/components/follow/season/seasonUi"
import { useSeason } from "@/hooks/useTranscripts"
import { daysBetween, groupByDate, localToday, seasonPhase, type SeasonPhase } from "@/lib/seasonPhase"
import { FillArea } from "@/components/shared/Bounded"
import { FillSkeleton, KpiStrip, MarketCard } from "@/components/home/MarketFrame"
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
 * 홈 › 미국 시장 ④ 왼쪽 — 실적 시즌 칸 (시안 Home-US, ia-redesign §4.3·§4.28, D-325로 맨 위에서 ④로). 결론과 입구만 둔다(차트·종목 표는 탐색 › 컨콜).
 * 시즌 중: 판정 4칸 · 이번 시즌 시장이 따진 것(섹터 줄, 칸 안 스크롤) · 곧 발표 칩. 시즌 사이: 다음 시즌까지 D-n · 지난 시즌 정리 · 곧 발표 · 그 사이 볼 것.
 * 칸 높이는 고정(띠 ④). 오류는 이 칸만(§4.28) — 브리핑·거래대금 칸은 따로 불러온다.
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

/** note = 상태 한 줄(반응 집계 중 등) — 배지 대신 머리 ⓘ 툴팁에 붙인다(시안 Home-US) */
function Frame({ title, sub, note, link = { to: SEASON, label: "실적 시즌 전체" }, children }: { title: ReactNode; sub?: ReactNode; note?: string; link?: { to: string; label: string }; children: ReactNode }) {
  return (
    <MarketCard band="events" label="us.season">
      <BlockHead section title={title} sub={sub} info={note ? <>{INFO}<br />{note}</> : INFO} link={link} />
      {children}
    </MarketCard>
  )
}

/** 시즌 중 본문과 같은 뼈대(판정 4칸 · 섹터 줄) — 칸 높이는 고정이라 남은 자리를 채운다 */
function SeasonSkeleton() {
  return <div role="status" aria-label="데이터 불러오는 중" aria-busy="true" className="flex min-h-0 flex-1 flex-col gap-3">
    <div className="grid grid-cols-4 gap-px border">{[0, 1, 2, 3].map(i => <div key={i} className="space-y-2 px-3 py-2.5"><Skeleton className="h-3 w-16" /><Skeleton className="h-6 w-12" /></div>)}</div>
    <FillSkeleton rows={6} />
  </div>
}

/** 지난 시즌 정리 판정 — 발표 · 업종보다 강함 · 상회에도 약세 · 첫 반응 뒤집힘(시즌 중 4칸과 같은 이름) */
function Verdicts({ c }: { c: SeasonOverview["counts"] }) {
  return <div className="grid grid-cols-2 border">{([["발표", c.reported, c.followed, undefined], ["업종보다 강했다", c.up, undefined, "text-up-ink"],
    ["상회에도 약세", c.beat_down, undefined, "text-down-ink"], ["첫 반응 뒤집힘", c.reversed, undefined, undefined]] as const).map(([label, value, of, cls]) =>
    <div key={label} className="flex min-w-0 flex-col gap-0.5 px-3 py-2">
      <p className="truncate text-[11.5px] text-ink-3">{label}</p>
      <p className="font-display text-lg tabular-nums"><span className={cls}>{formatNumber(value)}</span>{of != null && <span className="text-xs text-ink-3"> / {formatNumber(of)}</span>}</p>
    </div>)}
  </div>
}

function InSeason({ d, today }: { d: SeasonOverview; today: string }) {
  const pending = d.reported.filter(r => r.d1 == null).length
  const sectors = d.sectors.filter(s => s.one_line)
  const upcoming = d.upcoming.filter(u => u.event_date >= today)
  const c = d.counts
  return <Frame title={d.season.label} sub={`미국 · 팔로우 ${formatNumber(c.followed)}`} note={pending > 0 ? `첫 거래일 반응을 아직 집계하고 있는 발표가 ${formatNumber(pending)}건 있어요.` : undefined}>
    <KpiStrip items={[
      { label: "발표", value: formatNumber(c.reported), of: `/ ${formatNumber(c.followed)}` },
      { label: "업종보다 강했다", value: formatNumber(c.up), of: `/ ${formatNumber(c.reactions)}` },
      { label: "상회에도 약세", value: formatNumber(c.beat_down), of: `/ ${formatNumber(c.beat)}` },
      { label: "첫 반응 뒤집힘", value: formatNumber(c.reversed) },
    ]} />
    {!sectors.length ? <p className="min-h-0 flex-1 text-sm text-ink-3">섹터 요약이 아직 없습니다. 반응 정리 {formatNumber(c.reactions)}/{formatNumber(c.reported)}</p>
      : <FillArea aria-label="이번 시즌 시장이 따진 것"><ul>{sectors.map(s => (
        <li key={s.key} className="border-b">
          <Link to={sectorPath(s.key)} className="grid grid-cols-[150px_minmax(0,1fr)] gap-3 py-[9px] hover:bg-muted/50 max-sm:grid-cols-[110px_minmax(0,1fr)]">
            <span className="flex flex-col items-start gap-1 text-[13px] font-semibold">{s.name}<VerdictBadge verdict={s.verdict} /></span>
            <span className="line-clamp-2 text-[12.5px] leading-[1.6] text-ink-2">{s.one_line}</span>
          </Link>
        </li>
      ))}</ul></FillArea>}
    {!!upcoming.length && <section aria-label="곧 발표" className="flex max-h-[26px] shrink-0 flex-wrap items-center gap-1.5 overflow-hidden">
      <h3 className="mr-1 text-xs font-normal text-ink-3">곧 발표</h3>
      {upcoming.slice(0, 8).map(u => <UpcomingChip key={`${u.ticker}-${u.event_date}`} u={u} today={today} />)}
    </section>}
  </Frame>
}

function UpcomingChip({ u, today }: { u: SeasonItem; today: string }) {
  const n = daysBetween(today, u.event_date)
  return <Badge asChild variant="outline" className="h-[26px] gap-1 rounded-full px-2.5 font-mono text-xs font-normal">
    <Link to={u.transcript_id ? `/follow/transcripts?t=${u.transcript_id}` : `/us/${u.ticker}`} title={`${u.name ?? u.ticker} · ${u.event_date}${u.confirmed ? "" : " (예상일)"}`}>
      <span className={n <= 1 ? "text-up-ink" : "text-muted-foreground"}>{n === 0 ? "오늘" : `D-${n}`}</span>
      <span className="font-medium text-foreground">{u.ticker}</span>
    </Link>
  </Badge>
}

/** 시즌 사이 빈 상태 (§4.28) — 판정 줄·섹터 줄 대신 다음 시즌까지 D-n · 지난 시즌 정리 · 곧 발표 · 그 사이 볼 것 */
function BetweenSeasons({ base, phase, today }: { base: SeasonOverview; phase: Extract<SeasonPhase, { state: "between" }>; today: string }) {
  const { next, last, daysToNext } = phase
  return <Frame title={next ? <span className="flex items-baseline gap-2">다음 실적 시즌까지 <span className="font-mono">D-{formatNumber(daysToNext)}</span></span> : "실적 시즌 사이"}
    sub={next ? `${next.label.replace(" 실적 시즌", " 시즌")} · ${mmdd(next.first)} 첫 발표` : undefined}>
    <FillArea aria-label="시즌 사이">
      <div data-season-state="between" className="grid gap-px border bg-border">
        <LastSeason base={base} last={last} />
        <NextUpcoming base={base} next={next} today={today} />
        <section aria-label="그 사이 볼 것" className="bg-card p-3">
          <h3 className="mb-2 text-xs font-semibold">그 사이 볼 것</h3>
          <ul className="divide-y text-[13px]">
            <li><a href="#us-briefing" className="flex justify-between gap-2 py-2 hover:underline">어젯밤 미국장 브리핑<span className="text-xs text-muted-foreground">위 ② 칸</span></a></li>
            <li><Link to="/home/macro" className="flex justify-between gap-2 py-2 hover:underline">홈 › 매크로<span className="text-xs text-muted-foreground">추세·금리·온도 ›</span></Link></li>
            <li><Link to={last ? `${SEASON}&season=${last.key}` : SEASON} className="flex justify-between gap-2 py-2 hover:underline">지난 시즌 콜 다시 읽기<span className="text-xs text-muted-foreground">탐색 › 컨콜 ›</span></Link></li>
          </ul>
        </section>
      </div>
    </FillArea>
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
        <Verdicts c={d.counts} />
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
