import { QueryState } from "@/components/shared/QueryState"
import { Link, useSearchParams } from "react-router-dom"
import { Markdown } from "@/components/shared/Markdown"
import { Lightbulb, Loader2, MonitorPlay, RefreshCw, Rss, Send } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { sourceDossierQuery, sourceSummaryQuery } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import type { DossierSummary, SourceDossier } from "@/types"
import { useRefreshSource, type RefreshKind } from "@/hooks/useRefreshSource"

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

  const query = useQuery(sourceDossierQuery(kind, key))
  const { data } = query
  // 계산 쿼리: stale일 때만 발화. 결과 불변(staleTime ∞) — 재방문 시 즉시 표시.
  const summary = useQuery(sourceSummaryQuery(kind, key, !!data?.summary_stale))
  const refresher = useRefreshSource()

  if (!kind || !key) return <ErrorState message="소스 정보가 없습니다 (kind/key 필요)" />
  return <QueryState query={query} loading={<SourceSkeleton />} isEmpty={() => false}>{data => {
    const stocks = data.top_entities.filter((e) => e.link_type === "stock")
    const tags = data.top_entities.filter((e) => e.link_type !== "stock")

    return (
      <PageContainer width="reading" gap="sm">
        {/* 헤더 — 피드에서 들어오는 화면이라 돌아가는 길을 둔다(ia-redesign §4.33) */}
        <div className="space-y-1">
          <Link to="/feed" className="text-[12.5px] text-ink-3 hover:text-ink">‹ 피드 · 팔로우한 소스</Link>
          <div className="flex items-center gap-2 flex-wrap">
            {data.kind === "telegram"
              ? <Send className="h-4 w-4 text-muted-foreground" />
              : data.kind === "youtube"
              ? <MonitorPlay className="h-4 w-4 text-muted-foreground" />
              : <Rss className="h-4 w-4 text-muted-foreground" />}
            <h1 className="font-display text-page font-normal tracking-[-0.02em]">{data.name}</h1>
            {data.author && <span className="text-sm text-muted-foreground">{data.author}</span>}
            <Badge>
              {data.kind === "telegram" ? "텔레그램" : data.kind === "youtube" ? "유튜브" : "블로그"}
            </Badge>
            {!data.is_active && <Badge variant="outline">숨김 — 내 피드·답변 제외</Badge>}
            {(data.kind === "telegram" || data.kind === "youtube" || data.kind === "blog") && (
              <Button variant="outline" size="sm" className="h-7 rounded-lg px-2.5 text-[12.5px] text-ink-2" disabled={refresher.isRefreshing(data.kind as RefreshKind, key)}
                title="30분 주기를 기다리지 않고 이 소스의 새 글만 가져옵니다"
                onClick={() => refresher.refresh(data.kind as RefreshKind, key, data.name)}>
                <RefreshCw aria-hidden="true" className={refresher.isRefreshing(data.kind as RefreshKind, key) ? "animate-spin" : ""} />지금 수집
              </Button>
            )}
          </div>
          <p className="font-mono text-[12.5px] text-ink-3 tabular-nums">
            수집 {data.total_docs}건 · 최근 7일 {data.docs_7d}건
            {data.first_doc_at && data.last_doc_at
              ? ` · ${data.first_doc_at.slice(0, 10)} ~ ${data.last_doc_at.slice(0, 10)}`
              : data.last_doc_at && ` · 마지막 글 ${data.last_doc_at.slice(0, 10)}`}
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
                  <CardTitle className="text-[15px] font-semibold">주로 다루는 것 <span className="text-xs font-normal text-ink-3">최근 90일</span></CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-1.5">
                  {stocks.map((e) => (
                    <Link key={`s-${e.entity_id}`} to={e.aliases ? `/analyze/${e.aliases}/summary` : "#"}>
                      <Badge variant="outline" className="gap-1 hover:text-ink">
                        {e.name} <span className="text-muted-foreground tabular-nums">{e.count}</span>
                      </Badge>
                    </Link>
                  ))}
                  {tags.map((e) => (
                    <Link
                      key={`t-${e.entity_id}-${e.link_type}`}
                      to={`/feed?${e.link_type === "industry" ? "industry" : "topic"}=${encodeURIComponent(e.name)}`}
                    >
                      <Badge className="gap-1 hover:text-ink">
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
                <CardTitle className="text-[15px] font-semibold">최근 글</CardTitle>
              </CardHeader>
              <CardContent className="divide-y">
                {data.recent_docs.map((d) => (
                  <Link key={d.id} to={`/doc/${d.id}`} className="flex items-baseline gap-2 py-1.5 group">
                    <span className="text-sm truncate group-hover:underline">{d.title}</span>
                    <span className="ml-auto shrink-0 font-mono text-[11px] text-ink-3 tabular-nums">
                      {(d.published_at ?? "").slice(5, 10).replace("-", "/")}
                    </span>
                  </Link>
                ))}
                <Link to={`/feed?channel=${encodeURIComponent(`${data.kind}:${key}`)}`} className="block pt-2 text-caption text-muted-foreground hover:text-foreground">이 소스만 피드에서 보기 ›</Link>
              </CardContent>
            </Card>
          </>
        )}
      </PageContainer>
    )
  }}</QueryState>
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
    <Card className="border-line-2 bg-surface-2">
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-[15px] font-semibold">관점 프로필</CardTitle>
        {s?.created_at && (
          <span className="ml-auto font-mono text-xs text-ink-3 tabular-nums">
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
              <div className="flex gap-2 rounded-[10px] bg-hyp-tint px-3 py-2.5">
                <Lightbulb className="h-3.5 w-3.5 text-hyp shrink-0 mt-1" />
                <p className="text-[13px] leading-[1.6]"><span className="font-semibold whitespace-nowrap text-hyp">지난 프로필 이후</span> {s.insights}</p>
              </div>
            )}
            {!pending && failed && <p className="text-caption text-muted-foreground">새 글을 반영하지 못해 이전 프로필을 보여 드립니다. 다시 열면 재시도합니다.</p>}
            <Markdown className={pending ? "opacity-60" : ""}>{s.digest}</Markdown>
            <div className="text-right">
              <Badge variant="hyp">
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
      <Skeleton className="h-48 w-full rounded-card" />
      <Skeleton className="h-24 w-full rounded-card" />
    </PageContainer>
  )
}
