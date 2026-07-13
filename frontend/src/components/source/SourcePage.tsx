import { Link, useSearchParams } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import { Lightbulb, Loader2, MonitorPlay, Rss, Send } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { sourceDossierQuery, sourceSummaryQuery } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import type { DossierSummary, SourceDossier } from "@/types"

/**
 * /source?kind=telegram|blog&key= — 소스 도시에 (docs/specs/source-dossier.md)
 * "이 채널은 어떤 맥락 속에서 이런 말을 했지?" — 관점 프로필 + 주요 엔티티 + 최근 글.
 * 프로필은 열람 시점에 게으르게 생성: 지난 요약 이후 새 글이 있을 때만 LLM 호출.
 *
 * 상태관리: 도시에·프로필 생성 모두 (kind,key)로 키잉된 쿼리 (api/query.ts 규약).
 * 생성 중 다른 소스로 이동해도 각 응답은 자기 키 슬롯에만 적재 — 오염 불가.
 */
export default function SourcePage() {
  const [searchParams] = useSearchParams()
  const kind = searchParams.get("kind") ?? ""
  const key = searchParams.get("key") ?? ""

  const { data, isLoading, isError, refetch } = useQuery(sourceDossierQuery(kind, key))
  // 계산 쿼리: stale일 때만 발화. 결과 불변(staleTime ∞) — 재방문 시 즉시 표시.
  const summary = useQuery(sourceSummaryQuery(kind, key, !!data?.summary_stale))

  if (!kind || !key) return <ErrorState message="소스 정보가 없습니다 (kind/key 필요)" />
  if (isLoading) return <SourceSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const stocks = data.top_entities.filter((e) => e.link_type === "stock")
  const tags = data.top_entities.filter((e) => e.link_type !== "stock")

  return (
    <PageContainer width="reading" gap="sm">
      {/* 헤더 */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          {data.kind === "telegram"
            ? <Send className="h-4 w-4 text-muted-foreground" />
            : data.kind === "youtube"
            ? <MonitorPlay className="h-4 w-4 text-muted-foreground" />
            : <Rss className="h-4 w-4 text-muted-foreground" />}
          <h2 className="text-xl font-bold">{data.name}</h2>
          {data.author && <span className="text-sm text-muted-foreground">{data.author}</span>}
          <Badge variant="secondary" className="text-[10px]">
            {data.kind === "telegram" ? "텔레그램" : data.kind === "youtube" ? "유튜브" : "블로그"}
          </Badge>
          {!data.is_active && <Badge variant="outline" className="text-[10px]">숨김 — 내 피드·답변 제외</Badge>}
        </div>
        <p className="text-xs text-muted-foreground tabular-nums">
          수집 {data.total_docs}건 · 최근 7일 {data.docs_7d}건
          {data.first_doc_at && data.last_doc_at &&
            ` · ${data.first_doc_at.slice(0, 10)} ~ ${data.last_doc_at.slice(0, 10)}`}
        </p>
      </div>

      {data.total_docs === 0 ? (
        <EmptyState message="아직 수집된 글이 없습니다. 다음 수집 주기(30분)에 반영됩니다." />
      ) : (
        <>
          <ProfileCard
            data={data}
            fresh={summary.data}
            pending={summary.isFetching}
            failed={summary.isError}
          />

          {/* 주로 다루는 것 (90일 링크 집계) */}
          {data.top_entities.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">주로 다루는 것 <span className="text-[11px] font-normal text-muted-foreground">최근 90일</span></CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {stocks.map((e) => (
                  <Link key={`s-${e.entity_id}`} to={e.aliases ? `/analyze/${e.aliases}/summary` : "#"}>
                    <Badge variant="outline" className="text-xs gap-1 hover:border-primary hover:text-primary">
                      {e.name} <span className="text-muted-foreground tabular-nums">{e.count}</span>
                    </Badge>
                  </Link>
                ))}
                {tags.map((e) => (
                  <Link
                    key={`t-${e.entity_id}-${e.link_type}`}
                    to={`/feed?${e.link_type === "industry" ? "industry" : "topic"}=${encodeURIComponent(e.name)}`}
                  >
                    <Badge variant="secondary" className="text-xs gap-1 hover:text-primary">
                      {e.name} <span className="text-muted-foreground tabular-nums">{e.count}</span>
                    </Badge>
                  </Link>
                ))}
              </CardContent>
            </Card>
          )}

          {/* 최근 글 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">최근 글</CardTitle>
            </CardHeader>
            <CardContent className="divide-y">
              {data.recent_docs.map((d) => (
                <Link key={d.id} to={`/doc/${d.id}`} className="flex items-baseline gap-2 py-1.5 group">
                  <span className="text-sm truncate group-hover:underline">{d.title}</span>
                  <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
                    {(d.published_at ?? "").slice(0, 10)}
                  </span>
                </Link>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </PageContainer>
  )
}

function ProfileCard({ data, fresh, pending, failed }: {
  data: SourceDossier
  fresh: DossierSummary | undefined
  pending: boolean
  failed: boolean
}) {
  // 생성 쿼리 결과 우선, 없으면 도시에에 실린 캐시 프로필
  const s = fresh ?? data.summary
  return (
    <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]">
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm">관점 프로필</CardTitle>
        {s?.created_at && (
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            {s.created_at.slice(0, 10)} 기준 · 최근 {s.doc_count}건
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {pending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            새 글을 반영해 프로필 생성 중… (수십 초 걸릴 수 있습니다)
          </div>
        )}
        {!pending && failed && !s?.digest && (
          <p className="text-xs text-muted-foreground py-2">
            프로필 생성에 실패했습니다. 잠시 후 다시 열람하면 재시도됩니다.
          </p>
        )}
        {!pending && !failed && !s?.digest && (
          <p className="text-xs text-muted-foreground py-2">
            아직 프로필이 없습니다. LLM 엔진이 연결되면 열람 시 자동 생성됩니다.
          </p>
        )}
        {s?.digest && (
          <>
            {s.insights && (
              <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
                <Lightbulb className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
                <p className="text-xs"><span className="font-semibold text-hypothesis">지난 프로필 이후</span> {s.insights}</p>
              </div>
            )}
            <div className={`prose prose-sm dark:prose-invert max-w-none text-sm [&_h3]:text-[13px] [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:my-1.5 ${pending ? "opacity-60" : ""}`}>
              <ReactMarkdown>{s.digest}</ReactMarkdown>
            </div>
            <div className="text-right">
              <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                AI 프로필 · 열람 시점 갱신
              </Badge>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function SourceSkeleton() {
  return (
    <PageContainer width="reading" gap="sm">
      <Skeleton className="h-7 w-64" />
      <Skeleton className="h-4 w-80" />
      <Skeleton className="h-48 w-full rounded-xl" />
      <Skeleton className="h-24 w-full rounded-xl" />
    </PageContainer>
  )
}
