import { useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, ChevronDown, GraduationCap,
  Info, Newspaper, Share2, TrendingUp } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { formatKstDateTime, formatNumber, formatUsd, formatPercent, formatRelativeTime } from "@/utils/format"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useUsBriefing, useUsBriefingDates } from "@/hooks/useUsBriefing"
import { UsBriefingSourcesDialog } from "@/components/home/UsBriefingSourcesDialog"
import type { UsBriefing, UsBriefingSource, UsMoverBrief } from "@/types"

/**
 * 홈 상단 — 어젯밤 미국장 브리핑 (docs/specs/us-briefing.md). 아침 분위기 파악 가속기.
 * **2문단 종합(D-206)**: 매크로(지정 채널·미국 매체에서 인용 검증된 이슈, `[n]` 원문 링크) + 거래대금 기업 이슈.
 * 과거 브리핑은 헤더 날짜 셀렉터로 조회(읽기 전용). 상위 20 전체는 Collapsible.
 * 5-state: Loading / Error / Partial(stale·묵은 스냅샷·synthesis=null) / Empty / Ideal.
 */
/** 위젯 안에 넣을 때 — 바깥 카드 틀과 제목은 위젯 틀이 맡는다 */
const EMBED = "gap-3 border-0 bg-transparent py-0 shadow-none [&>[data-slot=card-content]]:px-0 [&>[data-slot=card-header]]:px-0 [&_[data-slot=card-title]]:sr-only"
export function UsBriefingSection({ embedded = false }: { embedded?: boolean }) {
  const [pickedDate, setPickedDate] = useState<string | null>(null)
  const { data, isLoading, isError, refetch, refresh, refreshing } = useUsBriefing(pickedDate)
  const { data: dates = [] } = useUsBriefingDates()
  const [open, setOpen] = useState(false)

  if (isLoading) return <Skeleton className="h-80 w-full rounded-xl" />
  if (isError || !data || data.status === "error")
    return <ErrorState message={data?.error ?? "미국장 브리핑을 불러올 수 없습니다."} onRetry={() => refetch()} />
  if (data.movers.length === 0)
    return (
      <Card data-home-briefing className={embedded ? EMBED : undefined}>
        <CardHeader className="pb-2 flex flex-wrap items-start gap-3">
          <CardTitle className="text-card-title flex items-center gap-1.5">
            <TrendingUp className="h-4 w-4 text-primary" /> 어젯밤 미국장 브리핑
          </CardTitle>
          <div className="ml-auto flex items-center gap-1.5">
            <UsBriefingSourcesDialog />
            <RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트" />
          </div>
        </CardHeader>
        <CardContent>
          <EmptyState message={refreshing ? "전날 미국장을 불러오는 중…" : "‘지금 업데이트’를 눌러 전날 미국장 브리핑을 생성하세요."} />
        </CardContent>
      </Card>
    )

  const { clusters, idiosyncratic, movers, synthesis } = data
  // D-206 이전 서버 응답에는 두 필드가 없다 — 없다고 화면 전체가 죽지 않게 빈 배열로 읽는다
  const sources = synthesis?.sources ?? []
  const gaps = synthesis?.source_gaps ?? []
  const topShare = clusters[0]

  const controls = (
    <div className="ml-auto flex items-center gap-1">
      {dates.length > 1 && (
        <Select value={pickedDate ?? "latest"}
          onValueChange={(v) => setPickedDate(v === "latest" ? null : v)}>
          <SelectTrigger className="h-7 w-24 text-caption" aria-label="브리핑 날짜">
            <SelectValue placeholder="날짜" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="latest" className="text-xs">최신</SelectItem>
            {dates.map((d) => (
              <SelectItem key={d.trade_date} value={d.trade_date} className="text-xs">
                {d.trade_date}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {!embedded && <UsBriefingSourcesDialog />}
      {!pickedDate && <RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트 (전날 미국장 재수집·재종합)" />}
      {!embedded && <Link to="/us" className="text-caption text-muted-foreground hover:text-foreground">미국 종목 →</Link>}
    </div>
  )
  return (
    <Card data-home-briefing className={embedded ? EMBED : undefined}>
      {/* 위젯 안에서는 제목을 위젯 틀이 맡고 컨트롤은 기준 띠 오른쪽으로 — 한 줄을 아낀다 */}
      {!embedded && <CardHeader className="pb-2 flex flex-wrap items-start gap-3">
        <CardTitle className="text-card-title flex items-center gap-1.5">
          <TrendingUp className="h-4 w-4 text-primary" /> 어젯밤 미국장 브리핑
        </CardTitle>
        <span className="text-caption text-muted-foreground">전일 거래대금 상위 20 · 자금이 어디로 쏠렸나</span>
        {controls}
      </CardHeader>}

      <CardContent className="space-y-3">
        <SessionStrip data={data} past={!!pickedDate} controls={embedded ? controls : undefined} />
        {/* 핵심 요약 — 줄글 앞에 bullet로 먼저 (2026-10-17 이후 종합에만 있다) */}
        {!!synthesis?.key_points?.length && (
          <section aria-label="핵심 요약" className="rounded-lg bg-muted/40 px-3 py-2.5">
            <p className="mb-1.5 text-caption font-medium text-muted-foreground">핵심 요약</p>
            <ul className="list-disc space-y-1 pl-4 text-sm leading-relaxed marker:text-muted-foreground">
              {synthesis.key_points.map((point, i) => <li key={i}>{point}</li>)}
            </ul>
          </section>
        )}
        {/* 위젯 안에서는 지수 띠가 따로 있어 생략 */}
        {!embedded && data.indices.items.length > 0 && <div className="grid grid-cols-3 gap-3 border-b pb-4">
          {data.indices.items.slice(0, 3).map(index => <div key={index.name}>
            <p className="text-caption text-muted-foreground">{index.name}</p>
            <p className="mt-1 text-lg font-semibold tabular-nums @[420px]/market:text-2xl">{formatNumber(index.close)}</p>
            <p className={`text-caption tabular-nums ${chg(index.change_pct)}`}>{formatPercent(index.change_pct)}</p>
          </div>)}
        </div>}
        {data.status === "stale" && (
          <Banner tone="warn">실시간 갱신 실패 — 마지막 성공 데이터를 표시합니다.{data.error ? ` (${data.error})` : ""}</Banner>
        )}
        {data.status === "partial" && (
          <Banner tone="info">근거 스냅샷은 보존 기간이 지나 삭제됐습니다 — 저장된 종합만 표시합니다.</Banner>
        )}
        {!synthesis && data.status !== "partial" && (
          <Banner tone="info">LLM 종합이 아직 없습니다 — 아래 구조화 브리핑(섹터 쏠림·개별 이슈)만 표시합니다.</Banner>
        )}

        {gaps.length > 0 && (
          <Banner tone="info">빠진 재료: {gaps.join(" · ")}</Banner>
        )}

        {/* 종합 — 소제목 없이 한 편의 글로 (D-114). 매크로 문단의 [n]은 원문 링크 (D-206) */}
        {synthesis && (
          <div className="space-y-2">
            {[synthesis.index_summary, synthesis.drivers, synthesis.issues]
              .filter(Boolean)
              .map((para, i) => (
                <p key={i} className="text-reading text-foreground/90">
                  <CitedText text={para} sources={sources} />
                </p>
              ))}
          </div>
        )}

        {/* 섹터 쏠림 */}
        <div>
          <div className="mb-1 text-caption font-medium text-muted-foreground">
            섹터 쏠림 {topShare && <span className="text-foreground">· {topShare.label} {topShare.share_pct}%</span>}
          </div>
          <div className="space-y-1">
            {clusters.map((c) => (
              <div key={c.label} className="flex items-center gap-2 text-xs">
                <span className="w-24 shrink-0 truncate">{c.label}</span>
                <div className="relative h-3 flex-1 rounded bg-muted overflow-hidden">
                  <div className="absolute inset-y-0 left-0 bg-primary/70 rounded" style={{ width: `${c.share_pct}%` }} />
                </div>
                <span className="w-12 shrink-0 text-right tabular-nums">{c.share_pct}%</span>
                <span className={`w-14 shrink-0 text-right tabular-nums ${chg(c.median_change)}`}>{formatPercent(c.median_change)}</span>
                {/* 좁은 화면은 막대 폭이 줄마다 같도록 배지 자리를 늘 비워 둔다 */}
                <span className="flex w-10 shrink-0 justify-end sm:contents">{c.has_new && <Badge variant="outline" className="text-caption shrink-0 text-up border-up/40">신규</Badge>}</span>
                <span className="hidden sm:block text-caption text-muted-foreground truncate min-w-0 flex-1">{c.tickers.join(" · ")}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 개별 이슈 */}
        {idiosyncratic.length > 0 && (
          <div>
            <div className="mb-1 text-caption font-medium text-muted-foreground">개별 이슈 — 그룹으로 안 풀리는 움직임</div>
            <div className="grid grid-cols-1 @[620px]/market:grid-cols-2 gap-x-6 gap-y-1">
              {idiosyncratic.map((m) => <MoverRow key={m.ticker} m={m} />)}
            </div>
          </div>
        )}

        {/* 스터디 / 공유 후보 */}
        {synthesis && (synthesis.study_candidates.length > 0 || synthesis.share_candidates.length > 0) && (
          <div className="grid grid-cols-1 @[620px]/market:grid-cols-2 gap-3 pt-1">
            <CandidateList icon={GraduationCap} title="스터디 후보" items={synthesis.study_candidates} accent="text-hypothesis" />
            <CandidateList icon={Share2} title="공유 후보" items={synthesis.share_candidates} accent="text-primary" />
          </div>
        )}

        {/* 상위 20 전체 */}
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="flex items-center gap-1 text-caption text-muted-foreground hover:text-foreground">
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
            거래대금 상위 20 전체
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 grid grid-cols-1 @[620px]/market:grid-cols-2 gap-x-6 gap-y-0.5">
            {movers.map((m) => (
              <div key={m.ticker} className="flex items-center gap-2 py-0.5 text-sm min-w-0">
                <span className="w-5 text-right text-xs text-muted-foreground tabular-nums shrink-0">{m.rank}</span>
                <Link to={`/us/${m.ticker}`} className="font-semibold text-primary hover:underline shrink-0">{m.ticker}</Link>
                <span className="text-muted-foreground truncate min-w-0 flex-1 text-xs">{m.name}</span>
                {m.is_adr && <Badge variant="outline" className="text-caption shrink-0">ADR</Badge>}
                <span className={`w-14 text-right text-xs tabular-nums shrink-0 ${chg(m.change_pct)}`}>{m.change_pct != null ? formatPercent(m.change_pct) : "-"}</span>
                <span className="w-16 text-right shrink-0 font-medium tabular-nums text-xs">{m.dollar_volume != null ? formatUsd(m.dollar_volume) : "-"}</span>
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

/** 등락률 색 — 한국 컨벤션(상승=빨강 text-up, 하락=파랑 text-down). */
function chg(v: number | null): string {
  if (v == null || v === 0) return "text-muted-foreground"
  return v > 0 ? "text-up" : "text-down"
}

function MoverRow({ m }: { m: UsMoverBrief }) {
  const top = m.headlines?.[0]
  return (
    <div className="py-1 text-sm min-w-0">
      <div className="flex items-center gap-2 min-w-0">
        <Link to={`/us/${m.ticker}`} className="font-semibold text-primary hover:underline shrink-0">{m.ticker}</Link>
        <span className={`text-xs tabular-nums shrink-0 ${chg(m.change_pct)}`}>{m.change_pct != null ? formatPercent(m.change_pct) : ""}</span>
        <div className="flex items-center gap-1 min-w-0 flex-1 truncate">
          {m.flags.map((f) => (
            <Badge key={f} variant="outline" className={`text-caption shrink-0 ${f === "신규 진입" ? "text-up border-up/40" : ""}`}>{f}</Badge>
          ))}
        </div>
        {m.narrative && (
          <Link to={`/narrative?topic=${encodeURIComponent(m.narrative)}`}
            className="ml-auto shrink-0 max-w-[40%] truncate text-caption text-hypothesis hover:underline">{m.narrative}</Link>
        )}
      </div>
      {/* 개별 '왜' — US 원천 헤드라인 (D-097) */}
      {top ? (
        <a href={top.url ?? undefined} target="_blank" rel="noreferrer"
          className="mt-0.5 flex items-start gap-1 text-caption text-muted-foreground hover:text-foreground">
          <Newspaper className="h-3 w-3 shrink-0 mt-0.5" />
          <span className="truncate"><span className="text-foreground/70">{top.publisher}</span> · {top.title}</span>
        </a>
      ) : m.coverage === "uncovered" ? (
        <div className="mt-0.5 pl-1 text-caption text-muted-foreground">촉매 미상 · 스터디 후보</div>
      ) : null}
    </div>
  )
}

function CandidateList({ icon: Icon, title, items, accent }: {
  icon: React.ComponentType<{ className?: string }>; title: string; items: string[]; accent: string
}) {
  if (items.length === 0) return null
  return (
    <div className="rounded-lg border p-2.5">
      <div className={`mb-1.5 flex items-center gap-1.5 text-caption font-medium ${accent}`}>
        <Icon className="h-3.5 w-3.5" /> {title}
      </div>
      <ul className="space-y-1">
        {items.map((x, i) => <li key={i} className="text-xs leading-snug text-foreground/85">{x}</li>)}
      </ul>
    </div>
  )
}

/** `[n]` 출처 표식 → 위첨자 링크. 마우스를 올리면 출처(매체·제목·시각)를 보인다 — 하단 출처 목록 대신.
 * 출처 목록에 없는 번호는 평문으로 둔다(구 브리핑 호환). */
function CitedText({ text, sources }: { text: string; sources: UsBriefingSource[] }) {
  const byN = new Map(sources.map((s) => [s.n, s]))
  return <>{text.split(/(\[\d+\])/).map((part, i) => {
    const src = byN.get(Number(part.match(/^\[(\d+)\]$/)?.[1]))
    return src ? <sup key={i}><HoverCard openDelay={150} closeDelay={100}>
      <HoverCardTrigger asChild><SourceLink src={src} className="px-px text-primary hover:underline">{part}</SourceLink></HoverCardTrigger>
      <HoverCardContent side="top" className="w-80 space-y-1 text-sm">
        <p className="text-caption text-muted-foreground">[{src.n}] {src.publisher}{src.published_at ? ` · ${formatRelativeTime(src.published_at)}` : ""}</p>
        {src.title && <p className="font-medium leading-snug">{src.title}</p>}
        <p className="text-caption text-primary">{src.kind === "telegram" && src.doc_id != null ? "자료 상세 보기" : "원문 열기"} →</p>
      </HoverCardContent>
    </HoverCard></sup> : part
  })}</>
}

/** HoverCardTrigger(asChild)가 넘기는 포인터 이벤트·ref를 그대로 링크에 전달한다. */
function SourceLink({ src, className, children, ...rest }: { src: UsBriefingSource; className?: string; children: React.ReactNode } & React.ComponentProps<"a">) {
  if (src.kind === "telegram" && src.doc_id != null)
    return <Link {...rest} to={`/doc/${src.doc_id}`} className={className}>{children}</Link>
  return <a {...rest} href={src.url ?? undefined} target="_blank" rel="noreferrer" className={className}>{children}</a>
}

function Banner({ tone, children }: { tone: "warn" | "info"; children: React.ReactNode }) {
  const cls = tone === "warn" ? "bg-chart-warning/10 text-chart-warning" : "bg-muted text-muted-foreground"
  const Icon = tone === "warn" ? AlertTriangle : Info
  return (
    <div className={`flex items-start gap-1.5 rounded-md px-2 py-1.5 text-caption ${cls}`}>
      <Icon className="h-3.5 w-3.5 shrink-0 mt-0.5" /> <span>{children}</span>
    </div>
  )
}

/** SQLite UTC('YYYY-MM-DD HH:MM:SS') → KST 표기 */
const kst = (utc?: string | null) => utc ? formatKstDateTime(utc.includes("T") ? utc : `${utc.replace(" ", "T")}Z`) : "-"
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"]
const sessionLabel = (d: string) => `${d.slice(5).replace("-", "/")}(${WEEKDAY[new Date(`${d}T00:00:00Z`).getUTCDay()]})`

/**
 * 기준 띠 — '어젯밤'을 정말 반영했나를 먼저 밝힌다. 조용히 실패한 날(정기 생성 실패·늦은 실행)이 있어
 * 미국 장 날짜 · 어젯밤 여부 · 종합 생성 시각 · 정기 생성 결과를 한 줄에 둔다.
 * expected_session은 서버가 ET 16:00 마감·주말 제외로 계산(미국 공휴일 미반영).
 */
function SessionStrip({ data, past, controls }: { data: UsBriefing; past: boolean; controls?: React.ReactNode }) {
  const td = data.trade_date, expected = data.expected_session
  const fresh = !!td && !!expected && td === expected
  const run = data.last_run
  const runFailed = !!run && run.status !== "ok"
  return <div className={`rounded-lg border px-3 py-2 text-caption ${!past && !fresh ? "border-chart-warning/40 bg-chart-warning/5" : ""}`}>
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="font-medium text-foreground">미국 {td ? sessionLabel(td) : "-"} 장 마감 기준</span>
      {past ? <Badge variant="outline" className="text-[11px]">과거 브리핑</Badge>
        : fresh ? <Badge variant="outline" className="border-chart-green/40 text-[11px] text-chart-green">어젯밤 반영</Badge>
        : <Badge variant="outline" className="border-chart-warning/50 text-[11px] text-chart-warning">
            <AlertTriangle className="size-3" />어젯밤{expected ? ` ${sessionLabel(expected)}` : ""} 미반영
          </Badge>}
      {controls}
    </div>
    <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
      <span>종합 생성 {data.synthesis ? kst(data.synthesized_at) : "없음"}</span>
      <span>거래대금 수집 {kst(data.fetched_at)}</span>
      {!past && run && <span className={runFailed ? "text-chart-warning" : ""} title={run.summary ?? undefined}>
        정기 생성(06:30) {kst(run.ran_at)} {runFailed ? `실패 — ${run.summary ?? run.status}` : "성공"}
      </span>}
    </div>
  </div>
}
