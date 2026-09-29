import { useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, ChevronDown, GraduationCap,
  Info, Newspaper, Share2, TrendingUp } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { formatNumber, formatUsd, formatPercent } from "@/utils/format"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useUsBriefing, useUsBriefingDates } from "@/hooks/useUsBriefing"
import { UsBriefingSourcesDialog } from "@/components/home/UsBriefingSourcesDialog"
import type { UsBriefingSource, UsMoverBrief } from "@/types"

/**
 * 홈 상단 — 어젯밤 미국장 브리핑 (docs/specs/us-briefing.md). 아침 분위기 파악 가속기.
 * **2문단 종합(D-206)**: 매크로(지정 채널·미국 매체에서 인용 검증된 이슈, `[n]` 원문 링크) + 거래대금 기업 이슈.
 * 과거 브리핑은 헤더 날짜 셀렉터로 조회(읽기 전용). 상위 20 전체는 Collapsible.
 * 5-state: Loading / Error / Partial(stale·묵은 스냅샷·synthesis=null) / Empty / Ideal.
 */
export function UsBriefingSection() {
  const [pickedDate, setPickedDate] = useState<string | null>(null)
  const { data, isLoading, isError, refetch, refresh, refreshing } = useUsBriefing(pickedDate)
  const { data: dates = [] } = useUsBriefingDates()
  const [open, setOpen] = useState(false)

  if (isLoading) return <Skeleton className="h-80 w-full rounded-xl" />
  if (isError || !data || data.status === "error")
    return <ErrorState message={data?.error ?? "미국장 브리핑을 불러올 수 없습니다."} onRetry={() => refetch()} />
  if (data.movers.length === 0)
    return (
      <Card data-home-briefing>
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

  return (
    <Card data-home-briefing>
      <CardHeader className="pb-2 flex flex-wrap items-start gap-3">
        <CardTitle className="text-card-title flex items-center gap-1.5">
          <TrendingUp className="h-4 w-4 text-primary" /> 어젯밤 미국장 브리핑
        </CardTitle>
        <span className="text-caption text-muted-foreground">전일 거래대금 상위 20 · 자금이 어디로 쏠렸나</span>
        <div className="ml-auto flex items-center gap-1.5">
          {dates.length > 1 && (
            <Select value={pickedDate ?? "latest"}
              onValueChange={(v) => setPickedDate(v === "latest" ? null : v)}>
              <SelectTrigger className="w-36 text-caption">
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
          <UsBriefingSourcesDialog />
          {data.fetched_at && <FreshnessStamp asOf={data.fetched_at} />}
          {!pickedDate && <RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트 (전날 미국장 재수집·재종합)" />}
          <Link to="/us" className="text-caption text-muted-foreground hover:text-foreground">미국 종목 →</Link>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {data.indices.items.length > 0 && <div className="grid grid-cols-1 gap-3 border-b pb-4 @[420px]/market:grid-cols-3">
          {data.indices.items.slice(0, 3).map(index => <div key={index.name}>
            <p className="text-caption text-muted-foreground">{index.name}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{formatNumber(index.close)}</p>
            <p className={`text-caption tabular-nums ${chg(index.change_pct)}`}>{formatPercent(index.change_pct)}</p>
          </div>)}
        </div>}
        {data.status === "stale" && (
          <Banner tone="warn">실시간 갱신 실패 — 마지막 성공 데이터를 표시합니다.{data.error ? ` (${data.error})` : ""}</Banner>
        )}
        {/* '어젯밤'을 자처하는데 스냅샷이 며칠 묵었으면 프레임이 거짓이 된다 — 먼저 밝힌다 (D-112) */}
        {!pickedDate && (data.stale_days ?? 0) > 1 && (
          <Banner tone="warn">
            거래대금 스냅샷이 {data.stale_days}일 전({data.trade_date}) 것입니다 — ‘지금 업데이트’로 갱신하세요.
          </Banner>
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
            {sources.length > 0 && <SourceList sources={sources} />}
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
                {c.has_new && <Badge variant="outline" className="text-caption shrink-0 text-up border-up/40">신규</Badge>}
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

/** `[n]` 출처 표식 → 위첨자 링크. 출처 목록에 없는 번호는 평문으로 둔다(구 브리핑 호환). */
function CitedText({ text, sources }: { text: string; sources: UsBriefingSource[] }) {
  const byN = new Map(sources.map((s) => [s.n, s]))
  return <>{text.split(/(\[\d+\])/).map((part, i) => {
    const src = byN.get(Number(part.match(/^\[(\d+)\]$/)?.[1]))
    return src ? <sup key={i}><SourceLink src={src} className="px-px text-primary hover:underline">{part}</SourceLink></sup> : part
  })}</>
}

function SourceLink({ src, className, children }: { src: UsBriefingSource; className?: string; children: React.ReactNode }) {
  const label = `${src.publisher}${src.title ? ` · ${src.title}` : ""}`
  if (src.kind === "telegram" && src.doc_id != null)
    return <Link to={`/doc/${src.doc_id}`} title={label} className={className}>{children}</Link>
  return <a href={src.url ?? undefined} target="_blank" rel="noreferrer" title={label} className={className}>{children}</a>
}

function SourceList({ sources }: { sources: UsBriefingSource[] }) {
  return (
    <ol className="space-y-0.5 border-t pt-2">
      {sources.map((s) => (
        <li key={s.n} className="flex min-w-0 gap-1.5 text-caption text-muted-foreground">
          <span className="shrink-0 tabular-nums">[{s.n}]</span>
          <SourceLink src={s} className="min-w-0 truncate hover:text-foreground">
            <span className="text-foreground/70">{s.publisher}</span>{s.title ? ` · ${s.title}` : ""}
          </SourceLink>
        </li>
      ))}
    </ol>
  )
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
