import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import ReactMarkdown from "react-markdown"
import { Check, ChevronDown, ChevronUp, Lightbulb, X } from "lucide-react"
import api from "@/api/client"
import { toast } from "sonner"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { useSpineFeed } from "@/hooks/useSpineFeed"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { SignalCard } from "@/components/shared/SignalCard"
import { formatRelativeTime } from "@/utils/format"

/**
 * analyze/:stockCode/mentions — 이 종목의 언급·신호 이력 (product-v2.md P1)
 * 디테일 = 상태의 전체: 이 종목에 대해 척추가 아는 모든 문서·신호.
 */
export default function MentionsPage({ stockCode }: { stockCode: string }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Number(searchParams.get("page") ?? "1")

  const feed = useSpineFeed({ stock: stockCode, page, size: 15 })
  const signals = useSpineSignals(undefined, 90)

  if (feed.isLoading || signals.isLoading) return <MentionsSkeleton />
  if (feed.isError || !feed.data) return <ErrorState onRetry={() => feed.refetch()} />

  const stockSignals = (signals.data?.items ?? []).filter((s) => s.stock_code === stockCode)
  const totalPages = Math.max(1, Math.ceil(feed.data.total / feed.data.size))

  return (
    <div className="space-y-5">
      <DigestSection stockCode={stockCode} />

      <KeywordsSection stockCode={stockCode} />

      {/* 신호 이력 (최근 90일) */}
      {stockSignals.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">신호 이력 (90일)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {stockSignals.map((s) => (
                <SignalCard key={s.id} signal={s} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 언급 문서 */}
      <Card>
        <CardHeader className="pb-2 flex-row items-baseline justify-between">
          <CardTitle className="text-sm">언급 문서 {feed.data.total}건</CardTitle>
          <FreshnessStamp asOf={feed.data.as_of} />
        </CardHeader>
        <CardContent>
          {feed.data.items.length === 0 ? (
            <EmptyState message="아직 이 종목을 언급한 수집 문서가 없습니다." />
          ) : (
            <ul className="divide-y">
              {feed.data.items.map((doc) => (
                <li key={doc.id} className="py-2.5 space-y-1">
                  <div className="flex items-center gap-2">
                    <SourceBadge sourceType={doc.source_type} />
                    {doc.channel && <span className="shrink-0 text-[11px] text-muted-foreground">{doc.channel}</span>}
                    <Link to={`/doc/${doc.id}`}
                       className="text-sm font-medium truncate hover:underline">
                      {doc.title || "(제목 없음)"}
                    </Link>
                    <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
                      {formatRelativeTime(doc.published_at)}
                    </span>
                  </div>
                  {doc.summary && (
                    <p className="text-xs text-muted-foreground line-clamp-2">{doc.summary}</p>
                  )}
                </li>
              ))}
            </ul>
          )}

          {totalPages > 1 && (
            <div className="flex items-center justify-end gap-2 pt-3">
              <span className="text-xs text-muted-foreground tabular-nums">{page}/{totalPages}</span>
              <Button variant="outline" size="sm" disabled={page <= 1}
                onClick={() => setSearchParams({ page: String(page - 1) })}>이전</Button>
              <Button variant="outline" size="sm" disabled={page >= totalPages}
                onClick={() => setSearchParams({ page: String(page + 1) })}>다음</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function MentionsSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-32 w-full rounded-xl" />
      <div className="border rounded-xl p-4 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  )
}


/* ---------- 언급 다이제스트 (1D · 7D 롤링, 2열) ---------- */

interface DigestItem {
  period: string
  period_start: string
  digest: string | null
  insights: string | null
  doc_count: number | null
  model: string | null
}

function DigestSection({ stockCode }: { stockCode: string }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
      <DigestCard stockCode={stockCode} period="1d" title="1D 요약" />
      <DigestCard stockCode={stockCode} period="7d" title="7D 롤링 요약" />
    </div>
  )
}

function DigestCard({ stockCode, period, title }: { stockCode: string; period: "1d" | "7d"; title: string }) {
  const [showArchive, setShowArchive] = useState(false)
  const { data } = useQuery({
    queryKey: ["spine", "digests", stockCode, period],
    queryFn: async () =>
      (await api.get("/api/spine/digests", { params: { stock: stockCode, period } })).data as {
        items: DigestItem[]
      },
    staleTime: 5 * 60_000,
  })

  const items = data?.items ?? []
  const latest = items[0]
  const archive = items.slice(1)

  return (
    <Card className="border-l-2 border-l-hypothesis flex flex-col">
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {latest && (
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            {latest.period_start} 기준 · {latest.doc_count ?? "-"}건
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {!latest ? (
          <p className="text-xs text-muted-foreground py-2">
            아직 요약이 없습니다. 언급이 수집되면 30분 주기로 생성됩니다.
          </p>
        ) : (
          <>
            {latest.insights && (
              <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
                <Lightbulb className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
                <p className="text-xs"><span className="font-semibold text-hypothesis">새로운 시각</span> {latest.insights}</p>
              </div>
            )}
            <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_h3]:text-[13px] [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:my-1.5">
              <ReactMarkdown>{latest.digest ?? ""}</ReactMarkdown>
            </div>
            <div className="text-right">
              <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                AI 요약 · {latest.model}
              </Badge>
            </div>

            {archive.length > 0 && (
              <div className="border-t pt-2">
                <button onClick={() => setShowArchive(!showArchive)}
                  className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
                  {showArchive ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  지난 요약 {archive.length}건
                </button>
                {showArchive && (
                  <div className="space-y-3 pt-2">
                    {archive.map((d) => (
                      <div key={d.period_start} className="rounded-md border px-3 py-2">
                        <div className="text-[11px] text-muted-foreground tabular-nums mb-1">
                          {d.period_start} · 문서 {d.doc_count ?? "-"}건
                        </div>
                        {d.insights && <p className="text-[11px] text-hypothesis mb-1">💡 {d.insights}</p>}
                        <div className="prose prose-sm dark:prose-invert max-w-none text-xs [&_p]:my-1">
                          <ReactMarkdown>{d.digest ?? ""}</ReactMarkdown>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 매칭 키워드 (이 종목을 무엇으로 잡는가) ---------- */

function KeywordsSection({ stockCode }: { stockCode: string }) {
  const qc = useQueryClient()
  const [input, setInput] = useState("")
  const { data } = useQuery({
    queryKey: ["spine", "keywords", stockCode],
    queryFn: async () =>
      (await api.get("/api/spine/keywords", { params: { stock: stockCode } })).data as {
        official_name: string | null
        keywords: { id: number; keyword: string; status: string }[]
      },
    staleTime: 60_000,
  })
  const add = useMutation({
    mutationFn: async (keyword: string) =>
      (await api.post("/api/spine/keywords", { stock: stockCode, keyword })).data as { retro_linked_docs: number },
    onSuccess: (d) => {
      toast.success(`키워드 등록 — 기존 문서 ${d.retro_linked_docs}건에 소급 적용`)
      qc.invalidateQueries({ queryKey: ["spine", "keywords", stockCode] })
      qc.invalidateQueries({ queryKey: ["spine", "feed"] })
    },
  })
  const remove = useMutation({
    mutationFn: async (id: number) => api.delete(`/api/spine/keywords/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "keywords", stockCode] }),
  })
  const approve = useMutation({
    mutationFn: async (id: number) =>
      (await api.post(`/api/spine/keywords/${id}/approve`)).data as { keyword: string; retro_linked_docs: number },
    onSuccess: (d) => {
      toast.success(`'${d.keyword}' 승인 — 기존 문서 ${d.retro_linked_docs}건 소급 링크`)
      qc.invalidateQueries({ queryKey: ["spine", "keywords", stockCode] })
      qc.invalidateQueries({ queryKey: ["spine", "feed"] })
    },
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">매칭 기준</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary" className="text-[10px]">{data?.official_name ?? "…"} (정식명)</Badge>
          <Badge variant="secondary" className="text-[10px]">{stockCode} (코드)</Badge>
          <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">
            + LLM 별칭 자동 인식
          </Badge>
          {(data?.keywords ?? []).filter((k) => k.status !== "proposed").map((k) => (
            <Badge key={k.id} variant="outline" className="text-[10px] gap-1 pr-1">
              {k.keyword}
              <button onClick={() => remove.mutate(k.id)} aria-label="키워드 삭제">
                <X className="h-2.5 w-2.5" />
              </button>
            </Badge>
          ))}
          {/* LLM 자동 제안 별칭 — 승인 시 결정적 매칭 편입 + 소급 링크 */}
          {(data?.keywords ?? []).filter((k) => k.status === "proposed").map((k) => (
            <Badge key={k.id} variant="outline"
              className="text-[10px] gap-1 pr-1 text-hypothesis border-hypothesis/40 bg-hypothesis/5">
              제안: {k.keyword}
              <button onClick={() => approve.mutate(k.id)} aria-label="별칭 승인" title="승인 (소급 링크)">
                <Check className="h-2.5 w-2.5" />
              </button>
              <button onClick={() => remove.mutate(k.id)} aria-label="별칭 거부" title="거부">
                <X className="h-2.5 w-2.5" />
              </button>
            </Badge>
          ))}
        </div>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (input.trim()) { add.mutate(input.trim()); setInput("") }
          }}
        >
          <Input value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="키워드 추가 (예: 슼하, SKH)" className="h-7 text-xs max-w-[220px]" />
          <Button type="submit" size="xs" variant="outline" disabled={add.isPending}>추가</Button>
          <span className="text-[10px] text-muted-foreground">등록 즉시 기존 문서에도 소급 적용됩니다</span>
        </form>
      </CardContent>
    </Card>
  )
}
