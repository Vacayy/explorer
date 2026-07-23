import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { FileText, Sparkles, ChevronRight } from "lucide-react"
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
interface FollowRow { ticker: string; company_name: string; group_label: string | null; n_calls: number; latest: LatestCall | null }
interface Quarter { transcript_id: number; fiscal_year: number | null; fiscal_period: string | null; call_date: string | null; has_digest: boolean }
interface Detail { transcript_id: number; ticker: string; company_name: string; fiscal_year: number | null; fiscal_period: string | null; call_date: string | null; digest: string | null; body: string }

const periodOf = (y: number | null, p: string | null) => `FY${y ?? "?"} ${p ?? ""}`.trim()

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
      )}
    </PageContainer>
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
