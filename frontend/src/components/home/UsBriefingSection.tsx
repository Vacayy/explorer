import { useState } from "react"
import { Link } from "react-router-dom"
import { Activity, AlertTriangle, BarChart3, ChevronDown, Clock, GraduationCap, Gauge,
  Info, Newspaper, Share2, TrendingUp } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { formatUsd, formatPercent } from "@/utils/format"
import MultiLineChart from "@/components/charts/MultiLineChart"
import type { LineConfig } from "@/components/charts/MultiLineChart"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useUsBriefing, useUsBriefingDates } from "@/hooks/useUsBriefing"
import type { UsFlowBlock, UsMoverBrief } from "@/types"

/**
 * 홈 상단 — 어젯밤 미국장 브리핑 (docs/specs/us-briefing.md). 아침 분위기 파악 가속기.
 * **4섹션 종합(D-112)**: ① 지수 마감 ② 시장을 움직인 요인 ③ 거래대금 이슈 ④ 시계열 흐름.
 * 하루치 스냅샷에 지수·매크로·비중추이를 얹어 '오늘이 흐름의 어디쯤인지'를 읽게 한다.
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
      <Card>
        <CardHeader className="pb-2 flex-row items-center gap-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <TrendingUp className="h-4 w-4 text-primary" /> 어젯밤 미국장 브리핑
          </CardTitle>
          <div className="ml-auto"><RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트" /></div>
        </CardHeader>
        <CardContent>
          <EmptyState message={refreshing ? "전날 미국장을 불러오는 중…" : "‘지금 업데이트’를 눌러 전날 미국장 브리핑을 생성하세요."} />
        </CardContent>
      </Card>
    )

  const { clusters, idiosyncratic, movers, synthesis } = data
  const topShare = clusters[0]

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <TrendingUp className="h-4 w-4 text-primary" /> 어젯밤 미국장 브리핑
        </CardTitle>
        <span className="text-[11px] text-muted-foreground">전일 거래대금 상위 20 · 자금이 어디로 쏠렸나</span>
        <div className="ml-auto flex items-center gap-1.5">
          {dates.length > 1 && (
            <Select value={pickedDate ?? "latest"}
              onValueChange={(v) => setPickedDate(v === "latest" ? null : v)}>
              <SelectTrigger className="h-7 w-[124px] text-[11px]">
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
          {data.fetched_at && <FreshnessStamp asOf={data.fetched_at} />}
          {!pickedDate && <RefreshButton onClick={refresh} pending={refreshing} title="지금 업데이트 (전날 미국장 재수집·재종합)" />}
          <Link to="/us" className="text-[11px] text-muted-foreground hover:text-foreground">미국 종목 →</Link>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
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

        {/* 4섹션 종합 (D-112) — 지수 → 요인 → 이슈 → 흐름 */}
        {synthesis && (
          <div className="space-y-2.5">
            <Section icon={BarChart3} title="지수 마감" body={synthesis.index_summary}
              meta={data.indices.items.length > 0
                ? data.indices.items.map((i) => `${i.name} ${i.change_pct >= 0 ? "+" : ""}${i.change_pct}%`).join(" · ")
                  + (data.indices.as_of && data.indices.as_of !== data.trade_date ? ` (${data.indices.as_of})` : "")
                : undefined} />
            <Section icon={Gauge} title="시장을 움직인 요인" body={synthesis.drivers}
              meta={data.macro.items.length > 0
                ? `${data.macro.as_of ?? ""} · ${data.macro.lookback ?? ""}`
                  + (data.macro.signal?.signal ? ` · 신호등 ${data.macro.signal.signal}` : "")
                : undefined} />
            <Section icon={TrendingUp} title="거래대금 이슈" body={synthesis.issues} />
            <Section icon={Activity} title="시계열 흐름" body={synthesis.flow}
              meta={data.flow.dates.length > 0 ? `최근 스냅샷 ${data.flow.dates.length}개 대비` : undefined} />
          </div>
        )}

        {/* 섹터 비중 추이 — ④ 산문의 근거 (LLM 0). 숫자 나열보다 모양이 읽히도록 차트로 */}
        {data.flow.sectors.length > 1 && <FlowChart flow={data.flow} />}

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

/**
 * 섹터 거래대금 비중 추이 — ④ 산문의 근거.
 * lightweight-charts는 CSS 변수를 못 받아 리터럴 색을 쓴다(ReportCharts 선례).
 * 라이트·다크 양쪽에서 보이는 밝은 조합.
 */
const FLOW_COLORS = ["#38bdf8", "#a78bfa", "#fb923c", "#34d399"]

function FlowChart({ flow }: { flow: UsFlowBlock }) {
  const lines: LineConfig[] = flow.sectors.map((s, i) => ({
    key: `s${i}`, label: s.label, color: FLOW_COLORS[i % FLOW_COLORS.length], lineWidth: 2,
  }))
  // 날짜별 행으로 피벗 — 스냅샷이 있는 날만 점이 찍힌다(휴장·미수집 구간은 자연히 비어 있음)
  const byDate = new Map<string, Record<string, unknown>>()
  flow.sectors.forEach((sec, i) => {
    sec.series.forEach((pt) => {
      const row = byDate.get(pt.date) ?? { time: pt.date }
      row[`s${i}`] = pt.share_pct
      byDate.set(pt.date, row)
    })
  })
  const rows = [...byDate.values()].sort((a, b) => String(a.time).localeCompare(String(b.time)))

  return (
    <div className="rounded-lg border p-2.5">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
        <Clock className="h-3.5 w-3.5" /> 섹터 거래대금 비중 추이
        <span className="ml-auto tabular-nums">스냅샷 {flow.dates.length}개</span>
      </div>
      <MultiLineChart data={rows} lines={lines} height={168} formatValue={(v) => `${v.toFixed(1)}%`} />
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
        {flow.sectors.map((sec, i) => (
          <span key={sec.label} className="flex items-center gap-1 text-[10px]">
            <span className="h-1.5 w-1.5 rounded-full shrink-0"
              style={{ background: FLOW_COLORS[i % FLOW_COLORS.length] }} />
            <span className="text-muted-foreground">{sec.label}</span>
            <span className="font-medium text-foreground/80">{sec.trend?.label}</span>
            {sec.trend?.delta_pp != null && (
              <span className={`tabular-nums ${chg(sec.trend.delta_pp)}`}>
                {sec.trend.delta_pp > 0 ? "+" : ""}{sec.trend.delta_pp}%p
              </span>
            )}
          </span>
        ))}
      </div>
    </div>
  )
}

/** 종합 4섹션의 한 문단 — 제목 + (있으면) 결정적 수치 메타 + 산문. body 없으면 렌더 안 함. */
function Section({ icon: Icon, title, body, meta }: {
  icon: React.ComponentType<{ className?: string }>
  title: string; body: string; meta?: string
}) {
  if (!body) return null
  return (
    <div>
      <div className="mb-0.5 flex items-baseline gap-1.5">
        <Icon className="h-3.5 w-3.5 shrink-0 translate-y-0.5 text-muted-foreground" />
        <span className="text-[11px] font-medium text-foreground/80">{title}</span>
        {meta && <span className="text-[10px] tabular-nums text-muted-foreground truncate">{meta}</span>}
      </div>
      <p className="pl-5 text-sm leading-relaxed text-foreground/90">{body}</p>
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
