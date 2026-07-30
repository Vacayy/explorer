import { useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { FileText, Network, Sparkles, ChevronRight } from "lucide-react"
import api from "@/api/client"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { PageContainer } from "@/components/shared/PageContainer"
import { Markdown } from "@/components/shared/Markdown"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { ProxyDashboard } from "@/components/follow/ProxyDashboard"
import { cn } from "@/lib/utils"

/**
 * /follow/transcripts — 미국 기업 실적 컨콜 전용 페이지 (D-061, 2분할 브라우저).
 * 좌: 팔로우 기업 그룹 리스트(= 구독 관리) · 우: 선택 콜의 LLM 핵심 정리 → 원문 전문.
 * URL(?t=transcript_id)이 상태 소스. 정리는 POST compute(멱등·수 분)로 분리 생성.
 */
const GROUP_LABEL: Record<string, string> = {
  M7: "M7", hyperscaler: "하이퍼스케일러", nasdaq: "반도체·나스닥",
  "ai-datacenter": "AI 데이터센터", space: "우주", energy: "에너지",
  cpo: "CPO", software: "소프트웨어", web3: "Web3",
}
const GROUP_ORDER = ["M7", "hyperscaler", "nasdaq", "ai-datacenter", "space", "energy", "cpo", "software", "web3"]

interface LatestCall { transcript_id: number; fiscal_year: number | null; fiscal_period: string | null; call_date: string | null; has_digest: boolean }
interface FollowRow { ticker: string; company_name: string; group_label: string | null; n_calls: number; latest: LatestCall | null; last_report_date?: string | null; next_report_date?: string | null }
interface Quarter { transcript_id: number; fiscal_year: number | null; fiscal_period: string | null; call_date: string | null; has_digest: boolean }
interface TxNode { id: number; name: string; type: string; link_type: string }
interface TxEdge { rel_type: string; effect_direction: string | null; from: string; from_id: number; from_type: string; to: string; to_id: number; to_type: string }
interface Detail { transcript_id: number; ticker: string; company_name: string; fiscal_year: number | null; fiscal_period: string | null; call_date: string | null; digest: string | null; body: string; nodes?: TxNode[]; causal_edges?: TxEdge[] }

const NODE_LABEL: Record<string, string> = {
  company: "기업", sector: "섹터", theme: "테마", person: "인물",
  macro: "매크로", policy: "정책", event: "사건", industry: "산업", topic: "토픽",
}

/* 온톨로지 딥링크 칩 — 클릭 시 전역 인과 그래프의 그 노드로 초점 (?focus=id, D-089) */
function OntoChip({ id, name, type }: { id: number; name: string; type: string }) {
  return (
    <Link to={`/knowledge/ontology?focus=${id}`} title="온톨로지 그래프에서 이 노드 보기"
      className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs hover:border-primary hover:bg-primary/5 transition-colors">
      <span className="text-[9px] text-muted-foreground">{NODE_LABEL[type] ?? type}</span>
      <span className="font-medium">{name}</span>
    </Link>
  )
}

const periodOf = (y: number | null, p: string | null) => `FY${y ?? "?"} ${p ?? ""}`.trim()

/** 발표일까지 남은 일수 (오늘 0, 미래 양수, 지난 날 음수) */
function daysUntil(iso?: string | null): number | null {
  if (!iso) return null
  const d = new Date(iso + "T00:00:00")
  if (Number.isNaN(d.getTime())) return null
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - today.getTime()) / 86_400_000)
}
const ddayLabel = (n: number) => (n === 0 ? "오늘" : n > 0 ? `D-${n}` : `D+${-n}`)
const mmdd = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`

export default function TranscriptPage() {
  const [params, setParams] = useSearchParams()
  const selectedId = params.get("t")
  const view = params.get("view") === "proxies" ? "proxies" : "calls"
  const qc = useQueryClient()

  const setView = (v: string) => {
    const next = new URLSearchParams(params)
    if (v === "proxies") next.set("view", "proxies")
    else next.delete("view")
    setParams(next, { replace: true })
  }

  const { data: follows = [], isLoading, isError, refetch } = useQuery(
    apiQuery<FollowRow[]>({ key: ["spine", "transcript", "follow"], url: "/api/spine/transcript/follow", staleTime: STALE.short }),
  )

  const seed = useMutation({
    mutationFn: () => api.post("/api/spine/transcript/seed").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "transcript", "follow"] }),
  })

  const refreshCal = useMutation({
    mutationFn: () => api.post("/api/spine/transcript/calendar/refresh").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "transcript", "follow"] }),
  })

  const selectId = (id: number) => setParams({ t: String(id) }, { replace: true })

  if (isLoading) return <TranscriptSkeleton />
  if (isError) return <PageContainer><ErrorState onRetry={() => refetch()} /></PageContainer>

  const withCalls = follows.filter((f) => f.n_calls > 0)
  // 기본 선택: URL에 없으면 콜 있는 첫 기업의 최신
  const effectiveId = selectedId ?? (withCalls[0]?.latest?.transcript_id ? String(withCalls[0].latest!.transcript_id) : null)

  return (
    <PageContainer>
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-bold">Transcript</h2>
        <span className="text-xs text-muted-foreground">미국 기업 실적 컨퍼런스콜 · 팔로우 {follows.length}</span>
      </div>

      <Tabs value={view} onValueChange={setView}>
        <TabsList>
          <TabsTrigger value="calls">컨콜</TabsTrigger>
          <TabsTrigger value="proxies">프록시</TabsTrigger>
        </TabsList>
      </Tabs>

      {view === "proxies" ? (
        <ProxyDashboard />
      ) : (
      <>
      <UpcomingEarnings follows={follows} onSelect={selectId}
        onRefresh={() => refreshCal.mutate()} refreshing={refreshCal.isPending} />
      <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-4 items-start">
        {/* 좌 레일 — 팔로우 기업 그룹 (구독 관리 겸용) */}
        <Card className="md:sticky md:top-16">
          <CardContent className="p-2 max-h-[70vh] overflow-y-auto">
            {follows.length === 0 ? (
              <div className="p-3 space-y-3">
                <p className="text-xs text-muted-foreground">팔로우가 비어 있습니다. 기본 세트(미국 기업 21종)를 불러오세요.</p>
                <Button size="sm" onClick={() => seed.mutate()} disabled={seed.isPending}>
                  {seed.isPending ? "불러오는 중…" : "기본 세트 팔로우"}
                </Button>
              </div>
            ) : (
              <GroupedRail follows={follows} effectiveId={effectiveId} onSelect={selectId} />
            )}
          </CardContent>
        </Card>

        {/* 우 본문 — 선택 콜 상세 */}
        <div className="min-w-0">
          {effectiveId ? (
            <DetailPanel key={effectiveId} transcriptId={Number(effectiveId)} onSelect={selectId} />
          ) : (
            <Card><CardContent className="py-16">
              <EmptyState message="아직 수집된 컨콜이 없습니다 — 관리자에서 '컨콜 수집'을 실행하거나 기업을 팔로우하세요." />
            </CardContent></Card>
          )}
        </div>
      </div>
      </>
      )}
    </PageContainer>
  )
}

/* ---------- 곧 발표 (실적 발표일 캘린더, D-081) ---------- */
function UpcomingEarnings({ follows, onSelect, onRefresh, refreshing }: {
  follows: FollowRow[]; onSelect: (id: number) => void; onRefresh: () => void; refreshing: boolean
}) {
  const upcoming = useMemo(() => follows
    .map((f) => ({ f, d: daysUntil(f.next_report_date) }))
    .filter((x): x is { f: FollowRow; d: number } => x.d != null && x.d >= 0)
    .sort((a, b) => a.d - b.d)
    .slice(0, 12), [follows])

  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-muted-foreground">곧 발표 · 실적 캘린더</span>
          <Button variant="ghost" size="xs" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "갱신 중…(수십초)" : "발표일 갱신"}
          </Button>
        </div>
        {upcoming.length === 0 ? (
          <p className="text-xs text-muted-foreground py-1">예정된 발표일이 없습니다. '발표일 갱신'을 눌러 불러오세요.</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {upcoming.map(({ f, d }) => (
              <button
                key={f.ticker}
                onClick={() => f.latest && onSelect(f.latest.transcript_id)}
                disabled={!f.latest}
                title={`${f.company_name} · ${f.next_report_date}${f.latest ? "" : " (수집된 콜 없음)"}`}
                className={cn(
                  "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                  d <= 3 ? "border-primary/40 bg-primary/5" : "border-border",
                  f.latest ? "hover:bg-muted" : "opacity-60 cursor-default",
                )}
              >
                <span className="font-semibold tabular-nums">{f.ticker}</span>
                <span className={cn("tabular-nums", d <= 3 ? "text-primary font-medium" : "text-muted-foreground")}>
                  {ddayLabel(d)}
                </span>
                <span className="text-muted-foreground tabular-nums">{mmdd(f.next_report_date!)}</span>
              </button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 좌 레일: 그룹별 기업 리스트 ---------- */
function GroupedRail({ follows, effectiveId, onSelect }: {
  follows: FollowRow[]; effectiveId: string | null; onSelect: (id: number) => void
}) {
  const byGroup = useMemo(() => {
    const m = new Map<string, FollowRow[]>()
    for (const f of follows) {
      const g = f.group_label ?? "기타"
      if (!m.has(g)) m.set(g, [])
      m.get(g)!.push(f)
    }
    return m
  }, [follows])
  const groups = [...GROUP_ORDER.filter((g) => byGroup.has(g)), ...[...byGroup.keys()].filter((g) => !GROUP_ORDER.includes(g))]

  return (
    <div className="space-y-1">
      {groups.map((g) => (
        <Collapsible key={g} defaultOpen>
          <CollapsibleTrigger className="flex w-full items-center gap-1 px-2 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground">
            <ChevronRight className="h-3 w-3 transition-transform data-[state=open]:rotate-90" />
            {GROUP_LABEL[g] ?? g}
          </CollapsibleTrigger>
          <CollapsibleContent className="pl-1">
            {byGroup.get(g)!.map((f) => {
              const active = f.latest && String(f.latest.transcript_id) === effectiveId
              const dd = daysUntil(f.next_report_date)
              const imminent = dd != null && dd >= 0 && dd <= 14
              return (
                <button
                  key={f.ticker}
                  onClick={() => f.latest && onSelect(f.latest.transcript_id)}
                  disabled={!f.latest}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                    active ? "bg-accent text-accent-foreground font-semibold" : "hover:bg-muted",
                    !f.latest && "opacity-40 cursor-default",
                  )}
                >
                  <span className="font-medium tabular-nums">{f.ticker}</span>
                  <span className="truncate text-xs text-muted-foreground flex-1">{f.company_name}</span>
                  {imminent && (
                    <span className="text-[9px] font-medium tabular-nums shrink-0 rounded bg-primary/10 px-1 text-primary"
                      title={`다음 실적 ${f.next_report_date}`}>
                      {ddayLabel(dd!)}
                    </span>
                  )}
                  {f.latest ? (
                    <span className="text-[10px] text-muted-foreground shrink-0">{f.latest.fiscal_period}</span>
                  ) : (
                    <span className="text-[10px] text-muted-foreground shrink-0">–</span>
                  )}
                </button>
              )
            })}
          </CollapsibleContent>
        </Collapsible>
      ))}
    </div>
  )
}

/* ---------- 우 본문: 상세 (분기 셀렉터 + 정리 + 원문) ---------- */
function DetailPanel({ transcriptId, onSelect }: { transcriptId: number; onSelect: (id: number) => void }) {
  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<Detail>({ key: ["spine", "transcript", "detail", transcriptId], url: `/api/spine/transcript/detail/${transcriptId}`, staleTime: STALE.medium }),
  )
  const [wantDigest, setWantDigest] = useState(false)
  const computed = useQuery({
    ...apiComputeQuery<Detail>({ key: ["spine", "transcript", "digest", transcriptId], url: `/api/spine/transcript/detail/${transcriptId}/digest`, timeout: 300_000, enabled: wantDigest }),
  })

  if (isLoading) return <Card><CardContent className="py-6 space-y-3"><Skeleton className="h-5 w-48" /><Skeleton className="h-24 w-full" /></CardContent></Card>
  if (isError || !data) return <Card><CardContent className="py-10"><ErrorState onRetry={() => refetch()} /></CardContent></Card>

  const digest = computed.data?.digest ?? data.digest

  return (
    <Card>
      <CardContent className="py-5 space-y-4">
        {/* 헤더 + 분기 셀렉터 */}
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg truncate">{data.company_name}</span>
              <Badge variant="secondary" className="text-[11px]">{data.ticker}</Badge>
              <Link to={`/us/${data.ticker}`} className="text-xs text-primary hover:underline whitespace-nowrap"
                title="이 종목의 도시에(시세·밸류·투자 렌즈) 보기">도시에 →</Link>
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {periodOf(data.fiscal_year, data.fiscal_period)}{data.call_date ? ` · ${data.call_date}` : ""}
            </div>
          </div>
          <QuarterSelect ticker={data.ticker} current={transcriptId} onSelect={onSelect} />
        </div>

        {/* LLM 핵심 정리 (먼저) */}
        <section>
          <div className="flex items-center gap-1.5 mb-1.5 text-sm font-semibold">
            <Sparkles className="h-4 w-4 text-hypothesis" /> 핵심 정리
          </div>
          {digest ? (
            <div className="rounded-lg bg-muted/40 px-4 py-3"><Markdown>{digest}</Markdown></div>
          ) : computed.isFetching ? (
            <div className="rounded-lg bg-muted/40 px-4 py-3 space-y-2">
              <Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" />
              <p className="text-xs text-muted-foreground">LLM이 컨콜을 정리하는 중… (수 분 소요)</p>
            </div>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setWantDigest(true)}>
              <Sparkles className="h-3.5 w-3.5" /> 핵심 정리 생성 (LLM)
            </Button>
          )}
        </section>

        {/* 온톨로지 연결 (D-089) — 이 콜이 편입된 노드·인과, 클릭 시 그래프로 */}
        {((data.nodes?.length ?? 0) > 0 || (data.causal_edges?.length ?? 0) > 0) && (
          <section>
            <div className="flex items-center gap-1.5 mb-1.5 text-sm font-semibold">
              <Network className="h-4 w-4 text-muted-foreground" /> 온톨로지 연결
              <span className="text-[11px] font-normal text-muted-foreground">이 콜이 편입된 노드·인과 — 클릭 시 그래프로</span>
            </div>
            {(data.nodes?.length ?? 0) > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {data.nodes!.map((n) => <OntoChip key={n.id} id={n.id} name={n.name} type={n.type} />)}
              </div>
            )}
            {(data.causal_edges?.length ?? 0) > 0 && (
              <ul className="space-y-1">
                {data.causal_edges!.map((e, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-1">
                    <OntoChip id={e.from_id} name={e.from} type={e.from_type} />
                    <span className="text-[10px] text-muted-foreground">{e.rel_type === "BENEFITS_FROM" ? "← 수혜" : "→ 인과"}</span>
                    <OntoChip id={e.to_id} name={e.to} type={e.to_type} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* 원문 전문 (펼침) */}
        <Collapsible>
          <CollapsibleTrigger className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
            <FileText className="h-4 w-4" /> 원문 전문 펼치기
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-2 max-h-[60vh] overflow-y-auto rounded-lg border px-4 py-3 text-sm">
              <Markdown>{data.body}</Markdown>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

function QuarterSelect({ ticker, current, onSelect }: { ticker: string; current: number; onSelect: (id: number) => void }) {
  const { data: quarters = [] } = useQuery(
    apiQuery<Quarter[]>({ key: ["spine", "transcript", "company", ticker], url: `/api/spine/transcript/company/${ticker}`, staleTime: STALE.short }),
  )
  if (quarters.length <= 1) return null
  return (
    <Select value={String(current)} onValueChange={(v) => onSelect(Number(v))}>
      <SelectTrigger className="h-8 w-32 text-xs shrink-0"><SelectValue /></SelectTrigger>
      <SelectContent>
        {quarters.map((q) => (
          <SelectItem key={q.transcript_id} value={String(q.transcript_id)} className="text-xs">
            {periodOf(q.fiscal_year, q.fiscal_period)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function TranscriptSkeleton() {
  return (
    <PageContainer>
      <Skeleton className="h-6 w-32" />
      <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-4">
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    </PageContainer>
  )
}
