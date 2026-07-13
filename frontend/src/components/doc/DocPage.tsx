import { Link, useNavigate, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import ReactMarkdown from "react-markdown"
import { ArrowLeft, ExternalLink } from "lucide-react"
import api, { API_BASE } from "@/api/client"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { EntityChip } from "@/components/shared/EntityChip"
import { PageContainer } from "@/components/shared/PageContainer"
import { formatRelativeTime } from "@/utils/format"
import type { EntityTag, FeedDocument } from "@/types"

/**
 * /doc/:id — 문서 디테일. 수집한 raw content를 우리 사이트 안에서 열람.
 * 외부(텔레그램/블로그) 원문은 보조 버튼으로만 제공.
 */
export default function DocPage() {
  const { docId } = useParams<{ docId: string }>()
  const navigate = useNavigate()
  const { data: doc, isLoading, isError, refetch } = useQuery({
    queryKey: ["spine", "doc", docId],
    queryFn: async () => {
      const { data } = await api.get<FeedDocument>(`/api/spine/doc/${docId}`)
      return data
    },
    enabled: !!docId,
    staleTime: 5 * 60_000,
  })

  if (isLoading) return <DocSkeleton />
  if (isError || !doc) return <ErrorState message="문서를 찾을 수 없습니다." onRetry={() => refetch()} />

  const onChipFilter = (tag: EntityTag) => {
    if (tag.link_type === "stock" && tag.aliases) navigate(`/analyze/${tag.aliases}/summary`)
    else if (tag.link_type === "industry") navigate(`/feed?industry=${encodeURIComponent(tag.name)}`)
    else if (tag.link_type === "topic") navigate(`/feed?topic=${encodeURIComponent(tag.name)}`)
    else if (tag.link_type === "person") navigate(`/person?name=${encodeURIComponent(tag.name)}`)
  }

  return (
    <PageContainer width="reading" gap="sm">
      <Button variant="ghost" size="sm" onClick={() => navigate(-1)} className="h-auto border-0 p-0 font-normal flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:bg-transparent">
        <ArrowLeft className="size-3.5" /> 뒤로
      </Button>

      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <SourceBadge sourceType={doc.source_type} />
          {doc.channel && (doc.channel_kind && doc.channel_key ? (
            <Link
              to={`/source?kind=${doc.channel_kind}&key=${encodeURIComponent(doc.channel_key)}`}
              className="text-[11px] text-muted-foreground font-medium hover:text-primary hover:underline"
              title="소스 도시에 — 이 채널의 관점 프로필"
            >
              {doc.channel}
            </Link>
          ) : (
            <span className="text-[11px] text-muted-foreground font-medium">{doc.channel}</span>
          ))}
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {(doc.published_at || "").slice(0, 16).replace("T", " ")} · {formatRelativeTime(doc.published_at)}
          </span>
          {doc.enrich_model && (
            <Badge variant="outline" className="text-[10px] font-normal opacity-70">태깅: {doc.enrich_model}</Badge>
          )}
          {doc.url && (
            <Button asChild variant="outline" size="xs" className="ml-auto">
              <a href={doc.url} target="_blank" rel="noreferrer">
                <ExternalLink className="h-3 w-3" /> 원문
              </a>
            </Button>
          )}
        </div>
        <h2 className="text-lg font-bold leading-snug">{doc.title || "(제목 없음)"}</h2>
        {doc.entities.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {doc.entities.map((t) => (
              <EntityChip key={`${t.entity_id}-${t.link_type}`} tag={t} onFilter={onChipFilter} />
            ))}
          </div>
        )}
      </div>

      {/* AI 요약 (있으면) */}
      {doc.summary && (
        <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]">
          <CardContent className="py-2.5 text-xs text-muted-foreground">
            <span className="text-hypothesis font-medium mr-1">요약</span>{doc.summary}
          </CardContent>
        </Card>
      )}

      {/* 이미지 */}
      {doc.images.length > 0 && (
        <div className="space-y-2">
          {doc.images.map((img) => (
            <a key={img} href={`${API_BASE}/media/${img}`} target="_blank" rel="noreferrer">
              <img src={`${API_BASE}/media/${img}`} alt="" className="max-w-full rounded-lg border" loading="lazy" />
            </a>
          ))}
        </div>
      )}

      {/* 본문 — 유튜브는 opus 정리본(markdown), 그 외는 raw content */}
      <Card>
        <CardContent className="py-4">
          {doc.content?.trim() ? (
            doc.source_type === "youtube" ? (
              <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-1.5 [&_li]:my-0.5 [&_p]:my-1.5">
                <ReactMarkdown>{doc.content}</ReactMarkdown>
              </div>
            ) : (
              <div className="text-sm whitespace-pre-wrap leading-relaxed">{doc.content}</div>
            )
          ) : (
            <p className="text-sm text-muted-foreground">
              텍스트 본문이 없는 문서입니다{doc.images.length > 0 ? " (이미지 참조)" : ""}.
            </p>
          )}
        </CardContent>
      </Card>

      {/* 관련 문서 (임베딩 유사) */}
      <RelatedSection docId={doc.id} />

      {/* 이 문서가 언급한 종목의 디테일로 */}
      {doc.entities.filter((e) => e.link_type === "stock" && e.aliases).length > 0 && (
        <div className="text-xs text-muted-foreground">
          관련 종목:{" "}
          {doc.entities.filter((e) => e.link_type === "stock" && e.aliases).map((e, i, arr) => (
            <span key={e.entity_id}>
              <Link to={`/analyze/${e.aliases}/mentions`} className="text-primary hover:underline">{e.name}</Link>
              {i < arr.length - 1 && " · "}
            </span>
          ))}
        </div>
      )}
    </PageContainer>
  )
}

function DocSkeleton() {
  return (
    <PageContainer width="reading" gap="sm">
      <Skeleton className="h-4 w-16" />
      <Skeleton className="h-6 w-3/4" />
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-48 w-full rounded-xl" />
    </PageContainer>
  )
}


function RelatedSection({ docId }: { docId: number }) {
  const { data } = useQuery({
    queryKey: ["spine", "doc", docId, "related"],
    queryFn: async () =>
      (await api.get(`/api/spine/doc/${docId}/related`)).data as {
        id: number; source_type: string; title: string | null; published_at: string | null
      }[],
    staleTime: 10 * 60_000,
  })
  if (!data || data.length === 0) return null
  return (
    <Card>
      <CardContent className="py-3">
        <div className="text-[11px] text-muted-foreground mb-1.5">관련 문서 (의미 유사)</div>
        <ul className="space-y-1">
          {data.map((r) => (
            <li key={r.id} className="flex items-center gap-2 text-xs">
              <SourceBadge sourceType={r.source_type} />
              <Link to={`/doc/${r.id}`} className="truncate hover:underline">{r.title || "(제목 없음)"}</Link>
              <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                {(r.published_at || "").slice(0, 10)}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
