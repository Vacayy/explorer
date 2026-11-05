// 실적 시즌 · 한국 (?view=season&market=kr, ia-redesign §4.22, 시안 Season-KR, docs/specs/earnings-season.md §국내 시즌)
// 위계: 머리(시장·시즌 선택, 미국과 같은 머리) → KPI → 오늘 바뀐 것 → 발표 캘린더(?day=) → 반응이 좋았던·나빴던 발표
//       → 최근 발표 표(?kf=, 캘린더에서 고른 날) → 업종별 집계 | 아직 발표 전. 미국과 다른 점은 머리 ⓘ(D-303).
// 잠정실적 없이 분기보고서만 낸 회사(kind=quarterly, D-305)는 캘린더에 따로 쌓고 반응 집계·목록에는 넣되 '분기보고서' 태그를 붙인다.
// '발표 n곳'은 잠정실적 기준, 분기보고서만 낸 곳은 옆에 따로 센다.
// 국내에는 분기 컨센서스가 없어 상회·하회 판정과 실적×반응 교차 블록을 두지 않는다. 매출·영업이익은 2단계(본문 파싱) 전까지 비운다.
import { Link, useSearchParams } from "react-router-dom"
import { createContext, useContext, type ReactNode } from "react"
import { ChevronRight, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import FilterChips from "@/components/shared/FilterChips"
import { InfoTip } from "@/components/shared/InfoTip"
import { QueryState } from "@/components/shared/QueryState"
import { SeasonHeader, SeasonPicker } from "@/components/follow/season/SeasonHeader"
import { Meta, Pp, Section, mmdd, patchParams } from "@/components/follow/season/seasonUi"
import { useKrSeason } from "@/hooks/useTranscripts"
import { useDefaultWatchGroup } from "@/hooks/useGroups"
import { usePortfolio } from "@/hooks/usePortfolio"
import { filterAnnouncements, filterCounts, krCalendarBars, krPeak, periodicReportName, reactionExtremes, type KrFilter } from "@/lib/krSeason"
import { cn } from "@/lib/utils"
import { formatNumber, formatPercent, formatRatio } from "@/utils/format"
import type { KrAnnouncement, KrSeasonOverview } from "@/types"

const shortSeason = (key: string) => `${key.slice(0, 4)} Q${key.slice(-1)}`
const dossier = (code: string | null) => (code ? `/analyze/${code}/summary` : null)

export function KrSeasonView({ tabs }: { tabs: ReactNode }) {
  const [params] = useSearchParams()
  const q = useKrSeason(params.get("season"))
  const d = q.data
  return (
    <div className="space-y-4">
      {d ? (
        <SeasonHeader title={d.season.label}
          sub={<span className="inline-flex flex-wrap items-center gap-1.5">
            {shortSeason(d.season.key)} · {d.season.is_current ? "진행 중" : "지난 시즌"}
            <DifferencesTip />
            {d.coverage.partial && <>
              <Badge variant="outline" className="font-normal text-hypothesis">일부 기업만</Badge>
              <InfoTip label="수집 범위 설명">
                전 시장 공시 목록 수집이 {d.coverage.full_from ? mmdd(d.coverage.full_from) : "최근"}부터라 이 시즌은 보유·관심·시총 상위 기업의 공시만 있습니다.
              </InfoTip>
            </>}
          </span>}
          picker={<SeasonPicker options={d.seasons.map((s) => s.key)} value={d.season.key} currentKey={d.seasons.find((s) => s.is_current)?.key ?? null} />} />
      ) : q.isPending ? (
        <div className="space-y-2"><Skeleton className="h-8 w-72" /><Skeleton className="h-4 w-40" /></div>
      ) : <SeasonHeader title="국내 실적 시즌" />}
      {tabs}
      <QueryState query={q} loading={<KrSkeleton />} isEmpty={() => false}>{(data) => <KrBody d={data} />}</QueryState>
    </div>
  )
}

function KrBody({ d }: { d: KrSeasonOverview }) {
  const [, setParams] = useSearchParams()
  if (!d.announcements.length) {
    const prev = [...d.seasons].reverse().find((s) => s.key < d.season.key && s.count > 0)
    return (
      <Section>
        <div data-season-state="empty" className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">아직 이번 시즌 잠정실적 공시가 없습니다</h2>
          {prev && <div><Button variant="outline" size="sm" onClick={() => setParams((p) => patchParams(p, { season: prev.key, day: null, kf: null }))}>{prev.label} 마감 결과 보기</Button></div>}
        </div>
      </Section>
    )
  }
  return (
    <PeriodicName.Provider value={periodicReportName(d.season.key)}>
    <div className="surface-stack flex flex-col">
      <KpiRow d={d} />
      {d.season.is_current && <Changes d={d} />}
      <KrCalendar d={d} />
      <div className="surface-grid grid grid-cols-1 lg:grid-cols-2">
        <ExtremeList title="반응이 좋았던 발표" tip="시총 1조 이상 · 업종 대비 첫 반응 높은 순" items={reactionExtremes(d.announcements).good} empty="업종보다 강했던 큰 회사 발표가 아직 없습니다." />
        <ExtremeList title="반응이 나빴던 발표" tip="시총 1조 이상 · 업종 대비 첫 반응 낮은 순" items={reactionExtremes(d.announcements).bad} empty="업종보다 약했던 큰 회사 발표가 아직 없습니다." />
      </div>
      <RecentTable d={d} />
      <div className="surface-grid grid grid-cols-1 lg:grid-cols-2">
        <Groups d={d} />
        <Pending d={d} />
      </div>
    </div>
    </PeriodicName.Provider>
  )
}

/* ---------- KPI ---------- */
function Kpi({ label, value, sub, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <Card className={cn("py-0", className)}>
      <CardContent className="flex flex-col gap-0.5 py-3">
        <span className="text-caption text-muted-foreground">{label}</span>
        <span className="text-xl font-semibold tabular-nums">{value}</span>
        {sub && <span className="text-caption text-muted-foreground">{sub}</span>}
      </CardContent>
    </Card>
  )
}

function KpiRow({ d }: { d: KrSeasonOverview }) {
  const k = d.kpi
  const w = k.week
  return (
    <div className="surface-grid grid grid-cols-2 lg:grid-cols-5" aria-label="시즌 요약">
      <Kpi label="발표" value={<>{formatNumber(k.reported)}곳</>}
        sub={<><span className="whitespace-nowrap">지난 시즌 {formatNumber(k.prev_reported)}곳</span>{k.quarterly_only > 0 && (
          <span className="whitespace-nowrap" data-kr-quarterly-only> · {periodicReportName(d.season.key)}만 <span className="tabular-nums">{formatNumber(k.quarterly_only)}</span>곳</span>)}</>} />
      <Kpi label="이번 주 발표" value={w ? <>{formatNumber(w.n)}곳</> : "-"} sub={w?.first && w.last ? <>{mmdd(w.first)}{w.last !== w.first ? `–${mmdd(w.last)}` : ""}</> : undefined} />
      <Kpi label={<span className="inline-flex items-center gap-1">주가 Outperform 비율
        <InfoTip label="Outperform 비율 설명">첫 반응이 같은 업종 종목 중앙값보다 높았던 발표의 비율입니다({formatNumber(k.outperform_n)}/{formatNumber(k.outperform_base)}). 잠정실적 없이 {periodicReportName(d.season.key)}만 낸 회사도 보고서 접수일 기준으로 넣고, 다음 거래일 시세가 아직 없는 당일 반응은 뺍니다.</InfoTip></span>}
        value={formatRatio(k.outperform_ratio)}
        sub="첫 반응 기준" />
      <Kpi label="첫 반응 중앙값" value={<Pp v={k.median_x1} />} sub="업종 대비" />
      <Kpi className="max-lg:col-span-2" label="매출·영업이익 증감" value="-" sub={<span className="inline-flex items-center gap-1"><StageTag /> 본문 파싱 후</span>} />
    </div>
  )
}

const StageTag = () => <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal text-muted-foreground">2단계</Badge>

/* ---------- 오늘 바뀐 것 ---------- */
const NAMES_SHOWN = 4
const names = (xs: string[]) => xs.slice(0, NAMES_SHOWN).join("·") + (xs.length > NAMES_SHOWN ? ` 외 ${xs.length - NAMES_SHOWN}곳` : "")

function Changes({ d }: { d: KrSeasonOverview }) {
  const c = d.changes
  if (!c.added.length && !c.settled.length) return null
  return (
    <Card className="py-0">
      <CardContent className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3 text-sm">
        <span className="font-semibold">오늘 바뀐 것</span>
        {c.added.length > 0 && c.added_date && (
          <span>발표 추가 <b className="tabular-nums">{formatNumber(c.added.length)}</b>곳<span className="text-muted-foreground">({mmdd(c.added_date)})</span> · {names(c.added)}</span>
        )}
        {c.settled.length > 0 && c.settled_date && (
          <span className="text-muted-foreground">· 5일 반응 확정 {mmdd(c.settled_date)} 발표분({names(c.settled)})</span>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 발표 캘린더 ---------- */
const LABEL_MIN = 8

function KrCalendar({ d }: { d: KrSeasonOverview }) {
  const [params, setParams] = useSearchParams()
  const bars = krCalendarBars(d)
  const peak = krPeak(d.calendar)
  const picked = params.get("day")
  const max = Math.max(1, ...bars.map((b) => b.total + b.quarterly))
  const periodic = periodicReportName(d.season.key)
  const hasQuarterly = bars.some((b) => b.quarterly > 0)
  const today = d.today
  const q4 = d.season.key.endsWith("Q4")
  const pick = (date: string) => {
    setParams((p) => patchParams(p, { day: date === picked ? null : date }), { replace: true, preventScrollReset: true })
    if (date !== picked) requestAnimationFrame(() => document.getElementById("kr-announcements")?.scrollIntoView({ block: "start", behavior: "smooth" }))
  }
  return (
    <Section id="calendar">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="flex items-center gap-1 text-[15px] font-semibold">
          발표 캘린더
          <InfoTip label="발표 캘린더 설명">거래일마다 잠정실적 공시 수를 막대로 보입니다. 잠정실적 없이 {periodic}만 낸 회사는 점선 칸으로 위에 따로 쌓습니다. 막대를 누르면 아래 최근 발표 표가 그날 공시로 바뀝니다.</InfoTip>
        </h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-muted-foreground">
          {hasQuarterly && <span className="inline-flex items-center gap-x-3" aria-label="막대 범례">
            <span className="inline-flex items-center gap-1"><span className="inline-block size-2.5 bg-muted-foreground/40" />잠정실적</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block size-2.5 border border-dashed border-muted-foreground" />{periodic}만</span>
          </span>}
          {peak && <span>{mmdd(peak.date)} 하루 <span className="tabular-nums">{peak.total}</span>곳으로 가장 많음</span>}
        </div>
      </div>
      <div className="overflow-x-auto">
        <div className="flex h-36 min-w-max items-stretch gap-px pt-5 sm:min-w-0" role="group" aria-label="날짜별 공시 수">
          {bars.map((b, i) => {
            const isToday = b.date === today
            const isDeadline = b.date === d.deadline
            const sel = b.date === picked
            const prev = bars[i - 1]
            const tick = !prev || prev.date.slice(5, 7) !== b.date.slice(5, 7) || (prev.date.slice(8) < "15" && b.date.slice(8) >= "15")
            const any = b.total + b.quarterly
            return (
              <Button key={b.date} variant="ghost" disabled={!any} onClick={() => pick(b.date)} aria-pressed={sel}
                aria-label={`${mmdd(b.date)} 잠정실적 ${b.total}곳${b.quarterly ? ` · ${periodic}만 ${b.quarterly}곳` : ""}`}
                className={cn("relative h-full min-w-[6px] flex-1 flex-col items-stretch justify-end gap-0 rounded-none p-0 pb-4 hover:bg-muted disabled:opacity-100",
                  isToday && "border-l border-l-foreground", isDeadline && "border-r border-dashed border-r-muted-foreground", b.date > today && "bg-muted/40")}>
                {isToday && <span className="absolute -top-5 left-0.5 text-[10px] font-medium text-foreground">오늘</span>}
                {isDeadline && <span className="absolute -top-5 right-0.5 whitespace-nowrap text-[10px] text-muted-foreground">{q4 ? "사업보고서" : "분기보고서"} 마감 {mmdd(b.date)}</span>}
                {(b.total >= LABEL_MIN || (sel && any > 0)) && <span className="text-center text-[10px] tabular-nums text-muted-foreground">{sel && b.quarterly ? `${b.total}+${b.quarterly}` : b.total}</span>}
                {b.quarterly > 0 && <span data-kr-bar="quarterly" style={{ height: `${(b.quarterly / max) * 100}%` }}
                  className={cn("mx-auto block w-full max-w-[18px] border border-dashed border-muted-foreground", sel && "border-foreground")} />}
                {b.total > 0 && <span style={{ height: `${(b.total / max) * 100}%` }}
                  className={cn("mx-auto block w-full max-w-[18px] bg-muted-foreground/40", sel && "bg-foreground/80 outline-2 outline-offset-1 outline-foreground")} />}
                {tick && <span className="absolute bottom-0 left-0 whitespace-nowrap text-[10px] tabular-nums text-muted-foreground">{mmdd(b.date)}</span>}
              </Button>
            )
          })}
        </div>
      </div>
    </Section>
  )
}

/* ---------- 반응 값 ---------- */
function First({ a }: { a: KrAnnouncement }) {
  return (
    <span className="inline-flex items-baseline justify-end gap-1" title={a.r1 != null ? `주가 ${formatPercent(a.r1)}` : undefined}>
      <Pp v={a.x1} />
      {a.r1_state === "same_day" && <span className="text-[10px] text-muted-foreground">당일</span>}
    </span>
  )
}

function Five({ a }: { a: KrAnnouncement }) {
  if (a.r5_state === "pending") return <span className="text-caption text-muted-foreground">집계 중</span>
  return <span title={a.r5 != null ? `주가 ${formatPercent(a.r5)}` : undefined}><Pp v={a.x5} /></span>
}

/** 이 시즌 결산의 정기보고서 이름(분기·반기·사업보고서) — 태그 문구 */
const PeriodicName = createContext("분기보고서")

/** 잠정실적 없이 분기보고서만 낸 회사 표시(D-305) */
function KindTag({ a }: { a: KrAnnouncement }) {
  const name = useContext(PeriodicName)
  if (a.kind !== "quarterly") return null
  return <Badge variant="outline" className="h-4 shrink-0 px-1 text-[10px] font-normal text-muted-foreground" data-kr-kind="quarterly">{name}</Badge>
}

function CompanyName({ a, className }: { a: { corp_name: string; stock_code: string | null }; className?: string }) {
  const to = dossier(a.stock_code)
  return to ? <Link to={to} className={cn("truncate font-medium hover:underline", className)}>{a.corp_name}</Link>
    : <span className={cn("truncate font-medium", className)}>{a.corp_name}</span>
}

/* ---------- 반응이 좋았던·나빴던 발표 ---------- */
function ExtremeList({ title, tip, items, empty }: { title: string; tip: string; items: KrAnnouncement[]; empty: string }) {
  return (
    <Section>
      <h2 className="flex items-center gap-1 text-[15px] font-semibold">{title}<InfoTip label={`${title} 기준`}>{tip}. 첫 반응은 공시 전 종가에서 다음 거래일 종가까지, 5일은 공시 후 5거래일 종가까지입니다. 정기보고서 태그는 잠정실적 없이 정기보고서만 낸 회사입니다(보고서 접수일 기준).</InfoTip></h2>
      {items.length === 0 ? <Meta className="py-2">{empty}</Meta> : (
        <div className="flex flex-col text-sm">
          <div className="grid grid-cols-[minmax(0,1fr)_44px_70px_70px] gap-x-2 pb-1 text-caption text-muted-foreground">
            <span>회사 · 업종</span><span className="text-right">발표</span><span className="text-right">첫 반응</span><span className="text-right">5일</span>
          </div>
          {items.map((a) => (
            <div key={a.corp_code} className="grid grid-cols-[minmax(0,1fr)_44px_70px_70px] items-baseline gap-x-2 border-t py-2">
              <span className="flex min-w-0 flex-col"><span className="flex min-w-0 items-center gap-1"><CompanyName a={a} /><KindTag a={a} /></span><span className="truncate text-caption text-muted-foreground">{a.group ?? "-"}</span></span>
              <span className="text-right tabular-nums text-muted-foreground">{mmdd(a.rcept_dt)}</span>
              <span className="text-right font-semibold"><First a={a} /></span>
              <span className="text-right"><Five a={a} /></span>
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}

/* ---------- 최근 발표 표 ---------- */
const SHOWN = 20
const FILTERS: KrFilter[] = ["all", "big", "mine"]

function useMyCodes(): Set<string> {
  const watch = useDefaultWatchGroup()
  const portfolio = usePortfolio()
  return new Set([...(watch.data?.members ?? []).map((m) => m.stock_code), ...(portfolio.data?.holdings ?? []).map((h) => h.code)])
}

function RecentTable({ d }: { d: KrSeasonOverview }) {
  const [params, setParams] = useSearchParams()
  const mine = useMyCodes()
  const filter: KrFilter = FILTERS.find((f) => f === params.get("kf")) ?? "all"
  const day = params.get("day")
  const counts = filterCounts(d.announcements, mine, day)
  const rows = filterAnnouncements(d.announcements, filter, mine, day)
  const set = (patch: Record<string, string | null>) => setParams((p) => patchParams(p, patch), { replace: true, preventScrollReset: true })
  const label = { all: "전체", big: "시총 1조+", mine: "내 종목" } as const
  return (
    <Section id="kr-announcements">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1 text-[15px] font-semibold">
          최근 발표
          <InfoTip label="최근 발표 설명">첫 반응 = 공시 전 종가 → 다음 거래일 종가, 5일 = 공시 후 5거래일 종가까지이며 모두 같은 업종 종목 중앙값 대비입니다. 업종 종목이 5곳 미만이면 비웁니다. 정기보고서 태그는 잠정실적 없이 정기보고서만 낸 회사이며 반응은 보고서 접수일 기준입니다. 매출·영업이익은 공시 본문을 읽는 2단계에서 채웁니다.</InfoTip>
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          {day && <Button variant="secondary" size="sm" className="h-7 gap-1 text-xs" onClick={() => set({ day: null })} aria-label="날짜 선택 해제">{mmdd(day)} 공시<X className="size-3" /></Button>}
          <FilterChips value={filter} onChange={(v) => set({ kf: v === "all" ? null : v })}
            options={FILTERS.map((f) => ({ value: f, label: `${label[f]} ${formatNumber(counts[f])}` }))} />
        </div>
      </div>
      {rows.length === 0 ? <Meta className="py-2">{filter === "mine" ? "내 종목 중 이 조건의 발표가 아직 없습니다." : "이 조건의 발표가 없습니다."}</Meta> : (
        <Collapsible key={`${filter}:${day ?? ""}`}>
          <Table className="text-sm">
            <TableHeader>
              <TableRow>
                <TableHead>회사</TableHead>
                <TableHead className="hidden md:table-cell">업종</TableHead>
                <TableHead className="text-right">발표</TableHead>
                <TableHead className="hidden md:table-cell">기준</TableHead>
                <TableHead className="hidden lg:table-cell">매출 전년 대비 <StageTag /></TableHead>
                <TableHead className="hidden lg:table-cell">영업이익 전년 대비 <StageTag /></TableHead>
                <TableHead className="text-right">첫 반응<span className="max-md:hidden"> · 업종 대비</span></TableHead>
                <TableHead className="text-right">5일<span className="max-md:hidden"> · 업종 대비</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>{rows.slice(0, SHOWN).map((a) => <AnnRow key={a.corp_code} a={a} />)}</TableBody>
            {rows.length > SHOWN && <CollapsibleContent asChild><TableBody>{rows.slice(SHOWN).map((a) => <AnnRow key={a.corp_code} a={a} />)}</TableBody></CollapsibleContent>}
          </Table>
          {rows.length > SHOWN && (
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="group mx-auto mt-1 flex text-muted-foreground">
                <span className="group-data-[state=open]:hidden">{formatNumber(rows.length - SHOWN)}곳 더 보기</span>
                <span className="hidden group-data-[state=open]:inline">접기</span>
              </Button>
            </CollapsibleTrigger>
          )}
        </Collapsible>
      )}
    </Section>
  )
}

function Figure({ v }: { v: number | null | undefined }) {
  return v == null ? <span className="text-caption text-muted-foreground">본문 파싱 후</span> : <span className="tabular-nums">{formatPercent(v)}</span>
}

function AnnRow({ a }: { a: KrAnnouncement }) {
  return (
    <TableRow data-kr-row={a.corp_code}>
      <TableCell className="max-w-[160px]">
        <span className="flex min-w-0 flex-col"><span className="flex min-w-0 items-center gap-1"><CompanyName a={a} /><KindTag a={a} /></span><span className="truncate text-caption text-muted-foreground md:hidden">{a.group ?? "-"}</span></span>
      </TableCell>
      <TableCell className="hidden text-muted-foreground md:table-cell">{a.group ?? "-"}</TableCell>
      <TableCell className="text-right tabular-nums">{mmdd(a.rcept_dt)}</TableCell>
      <TableCell className="hidden text-muted-foreground md:table-cell">{a.basis ?? "-"}</TableCell>
      <TableCell className="hidden lg:table-cell"><Figure v={a.figures?.revenue_yoy} /></TableCell>
      <TableCell className="hidden lg:table-cell"><Figure v={a.figures?.op_income_yoy} /></TableCell>
      <TableCell className="text-right"><First a={a} /></TableCell>
      <TableCell className="text-right"><Five a={a} /></TableCell>
    </TableRow>
  )
}

/* ---------- 업종별 집계 ---------- */
function Groups({ d }: { d: KrSeasonOverview }) {
  return (
    <Section>
      <h2 className="flex items-center gap-1 text-[15px] font-semibold">업종별 집계<InfoTip label="업종별 집계 기준">발표한 회사의 첫 반응(주가) 중앙값과 업종보다 오른 곳의 비율입니다. 잠정실적 없이 정기보고서만 낸 회사도 셉니다. 당일 반응은 뺍니다. 업종을 누르면 산업 › 섹터로 갑니다.</InfoTip></h2>
      {d.groups.length === 0 ? <Meta className="py-2">업종을 아는 발표가 아직 없습니다.</Meta> : (
        <div className="flex flex-col text-sm">
          {d.groups.map((g) => (
            <Link key={g.group} to={`/map?group=${encodeURIComponent(g.group)}`}
              className="grid grid-cols-[minmax(0,1fr)_48px_64px_minmax(0,1fr)_12px] items-baseline gap-x-2 border-t py-2 first:border-t-0 hover:bg-muted/50">
              <span className="truncate font-medium">{g.group}</span>
              <span className="text-right tabular-nums text-muted-foreground" title={g.quarterly_n ? `정기보고서만 ${g.quarterly_n}곳 포함` : undefined}>{formatNumber(g.n)}곳</span>
              <span className={cn("text-right tabular-nums", g.median_r1 == null ? "text-muted-foreground" : g.median_r1 > 0 ? "text-up" : g.median_r1 < 0 ? "text-down" : "")}>{formatPercent(g.median_r1)}</span>
              <span className="truncate text-right text-caption text-muted-foreground">업종보다 오른 곳 <span className="tabular-nums">{formatRatio(g.up_ratio)}</span></span>
              <ChevronRight className="size-3 self-center text-muted-foreground" />
            </Link>
          ))}
        </div>
      )}
    </Section>
  )
}

/* ---------- 아직 발표 전 ---------- */
const PENDING_SHOWN = 8

function PendingRow({ p }: { p: KrSeasonOverview["pending"][number] }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-2 border-t py-2">
      <span className="flex min-w-0 items-baseline gap-2"><CompanyName a={p} /><span className="truncate text-caption text-muted-foreground">{p.group ?? "-"}</span></span>
      <span className="text-caption tabular-nums text-muted-foreground">지난 분기 {mmdd(p.prev_date)}</span>
    </div>
  )
}

function Pending({ d }: { d: KrSeasonOverview }) {
  const title = d.season.is_current ? "아직 발표 전" : "이 시즌 공시 없음"
  return (
    <Section>
      <h2 className="flex items-center gap-1 text-[15px] font-semibold">
        {title} <span className="tabular-nums font-normal text-muted-foreground">{formatNumber(d.pending.length)}곳</span>
        <InfoTip label={`${title} 기준`}>지난 시즌에는 잠정실적을 공시했지만 이 시즌에는 아직 잠정실적도 정기보고서도 내지 않은 회사를 시총 큰 순으로 보입니다. 지난 분기 공시일로 시점을 짐작할 수 있습니다.</InfoTip>
      </h2>
      {d.pending.length === 0 ? <Meta className="py-2">지난 시즌에 공시한 회사가 모두 공시했습니다.</Meta> : (
        <Collapsible className="flex flex-col text-sm">
          {d.pending.slice(0, PENDING_SHOWN).map((p) => <PendingRow key={p.corp_code} p={p} />)}
          {d.pending.length > PENDING_SHOWN && <>
            <CollapsibleContent className="flex flex-col">{d.pending.slice(PENDING_SHOWN).map((p) => <PendingRow key={p.corp_code} p={p} />)}</CollapsibleContent>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="group mx-auto mt-1 flex text-muted-foreground">
                <span className="group-data-[state=open]:hidden">{formatNumber(d.pending.length - PENDING_SHOWN)}곳 더 보기</span>
                <span className="hidden group-data-[state=open]:inline">접기</span>
              </Button>
            </CollapsibleTrigger>
          </>}
        </Collapsible>
      )}
    </Section>
  )
}

/* ---------- 국내 시즌이 미국과 다른 점 — 본문 블록 대신 머리 ⓘ(D-303, 화면 부연설명 금지) ---------- */
function DifferencesTip() {
  return (
    <InfoTip label="국내 시즌이 미국과 다른 점">
      DART 잠정실적 공시로 누가 언제 발표했는지와 발표 전후 주가(같은 업종 대비)를 봅니다. 매출·영업이익 증감은 공시 본문을 읽는 2단계부터 채웁니다.
      국내 분기 컨센서스가 없어 상회·하회는 판정하지 않습니다.
    </InfoTip>
  )
}

function KrSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-busy="true" aria-label="국내 실적 시즌 불러오는 중">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-20 rounded-card" />)}</div>
      <Skeleton className="h-44 w-full rounded-card" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2"><Skeleton className="h-72 rounded-card" /><Skeleton className="h-72 rounded-card" /></div>
      <Skeleton className="h-96 w-full rounded-card" />
    </div>
  )
}
