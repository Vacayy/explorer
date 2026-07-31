import { useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, ChevronDown, GraduationCap, Info, Newspaper, Share2, TrendingUp } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { formatUsd, formatPercent } from "@/utils/format"
import { useUsBriefing } from "@/hooks/useUsBriefing"
import type { UsMoverBrief } from "@/types"

/**
 * 홈 상단 — 어젯밤 미국장 브리핑 (docs/specs/us-briefing.md). 아침 분위기 파악 가속기.
 * 섹터 쏠림 + 개별 이슈 + 하루 1회 종합(분위기·스터디/공유 후보). 상위 20 전체는 Collapsible.
 * 5-state: Loading / Error(status=error·쿼리실패) / Partial(stale·synthesis=null) / Empty / Ideal.
 */
export function UsBriefingSection() {
  const { data, isLoading, isError, refetch } = useUsBriefing()
  const [open, setOpen] = useState(false)

  if (isLoading) return <Skeleton className="h-80 w-full rounded-xl" />
  if (isError || !data || data.status === "error")
    return <ErrorState message={data?.error ?? "미국장 브리핑을 불러올 수 없습니다."} onRetry={() => refetch()} />
  if (data.movers.length === 0)
    return <Card><CardContent className="py-6"><EmptyState message="표시할 종목이 없습니다." /></CardContent></Card>

  const { clusters, idiosyncratic, movers, synthesis } = data
  const topShare = clusters[0]

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <TrendingUp className="h-4 w-4 text-primary" /> 어젯밤 미국장 브리핑
        </CardTitle>
        <span className="text-[11px] text-muted-foreground">전일 거래대금 상위 20 · 자금이 어디로 쏠렸나</span>
        <div className="ml-auto flex items-center gap-2">
          {data.fetched_at && <FreshnessStamp asOf={data.fetched_at} />}
          <Link to="/us" className="text-[11px] text-muted-foreground hover:text-foreground">미국 종목 →</Link>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {data.status === "stale" && (
          <Banner tone="warn">실시간 갱신 실패 — 마지막 성공 데이터를 표시합니다.{data.error ? ` (${data.error})` : ""}</Banner>
        )}
        {!synthesis && (
          <Banner tone="info">LLM 종합이 아직 없습니다 — 아래 구조화 브리핑(섹터 쏠림·개별 이슈)만 표시합니다.</Banner>
        )}

        {/* 분위기 산문 */}
        {synthesis?.mood && (
          <p className="text-sm leading-relaxed text-foreground/90">{synthesis.mood}</p>
        )}

        {/* 어제 시장 담론 — 왜·무슨 얘기였나 (거래대금 × 내러티브 교차의 근거) */}
        {(data.market_themes.length > 0 || data.market_docs.length > 0) && (
          <div className="rounded-lg bg-muted/40 p-2.5 space-y-2">
            <div className="text-[11px] font-medium text-muted-foreground">어제 시장 담론 — 무슨 얘기였나</div>
            {data.market_themes.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {data.market_themes.slice(0, 10).map((t) => (
                  <Link key={t.name} to={`/narrative?topic=${encodeURIComponent(t.name)}`}>
                    <Badge variant="secondary" className="text-[10px] font-normal hover:bg-primary/10">
                      {t.name} <span className="ml-1 tabular-nums text-muted-foreground">{t.count}</span>
                    </Badge>
                  </Link>
                ))}
              </div>
            )}
            {data.market_docs.length > 0 && (
              <ul className="space-y-0.5">
                {data.market_docs.slice(0, 6).map((d) => (
                  <li key={d.id}>
                    <Link to={`/doc/${d.id}`} className="group flex items-center gap-1.5 text-xs min-w-0">
                      <Badge variant="outline" className="text-[9px] shrink-0">{d.source_type}</Badge>
                      <span className="truncate group-hover:underline">{d.title}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* 섹터 쏠림 */}
        <div>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">
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
                {c.has_new && <Badge variant="outline" className="text-[9px] shrink-0 text-up border-up/40">신규</Badge>}
                <span className="hidden sm:block text-[10px] text-muted-foreground truncate min-w-0 flex-1">{c.tickers.join(" · ")}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 개별 이슈 */}
        {idiosyncratic.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted-foreground">개별 이슈 — 그룹으로 안 풀리는 움직임</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
              {idiosyncratic.map((m) => <MoverRow key={m.ticker} m={m} />)}
            </div>
          </div>
        )}

        {/* 스터디 / 공유 후보 */}
        {synthesis && (synthesis.study_candidates.length > 0 || synthesis.share_candidates.length > 0) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
            <CandidateList icon={GraduationCap} title="스터디 후보" items={synthesis.study_candidates} accent="text-hypothesis" />
            <CandidateList icon={Share2} title="공유 후보" items={synthesis.share_candidates} accent="text-primary" />
          </div>
        )}

        {/* 상위 20 전체 */}
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
            거래대금 상위 20 전체
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-0.5">
            {movers.map((m) => (
              <div key={m.ticker} className="flex items-center gap-2 py-0.5 text-sm min-w-0">
                <span className="w-5 text-right text-xs text-muted-foreground tabular-nums shrink-0">{m.rank}</span>
                <Link to={`/us/${m.ticker}`} className="font-semibold text-primary hover:underline shrink-0">{m.ticker}</Link>
                <span className="text-muted-foreground truncate min-w-0 flex-1 text-xs">{m.name}</span>
                {m.is_adr && <Badge variant="outline" className="text-[9px] shrink-0">ADR</Badge>}
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
            <Badge key={f} variant="outline" className={`text-[9px] shrink-0 ${f === "신규 진입" ? "text-up border-up/40" : ""}`}>{f}</Badge>
          ))}
        </div>
        {m.narrative && (
          <Link to={`/narrative?topic=${encodeURIComponent(m.narrative)}`}
            className="ml-auto shrink-0 max-w-[40%] truncate text-[11px] text-hypothesis hover:underline">{m.narrative}</Link>
        )}
      </div>
      {/* 개별 '왜' — US 원천 헤드라인 (D-097) */}
      {top ? (
        <a href={top.url ?? undefined} target="_blank" rel="noreferrer"
          className="mt-0.5 flex items-start gap-1 text-[11px] text-muted-foreground hover:text-foreground">
          <Newspaper className="h-3 w-3 shrink-0 mt-0.5" />
          <span className="truncate"><span className="text-foreground/70">{top.publisher}</span> · {top.title}</span>
        </a>
      ) : m.coverage === "uncovered" ? (
        <div className="mt-0.5 pl-1 text-[10px] text-muted-foreground">촉매 미상 · 스터디 후보</div>
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
      <div className={`mb-1.5 flex items-center gap-1.5 text-[11px] font-medium ${accent}`}>
        <Icon className="h-3.5 w-3.5" /> {title}
      </div>
      <ul className="space-y-1">
        {items.map((x, i) => <li key={i} className="text-xs leading-snug text-foreground/85">{x}</li>)}
      </ul>
    </div>
  )
}

function Banner({ tone, children }: { tone: "warn" | "info"; children: React.ReactNode }) {
  const cls = tone === "warn" ? "bg-chart-warning/10 text-chart-warning" : "bg-muted text-muted-foreground"
  const Icon = tone === "warn" ? AlertTriangle : Info
  return (
    <div className={`flex items-start gap-1.5 rounded-md px-2 py-1.5 text-[11px] ${cls}`}>
      <Icon className="h-3.5 w-3.5 shrink-0 mt-0.5" /> <span>{children}</span>
    </div>
  )
}
