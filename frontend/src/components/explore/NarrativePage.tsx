import { useNavigate, useSearchParams } from "react-router-dom"
import { ArrowLeft, Loader2, Sparkles } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { Markdown } from "@/components/shared/Markdown"
import { PageContainer } from "@/components/shared/PageContainer"

/**
 * /narrative?topic= — 주제 내러티브 (theme_surge 고도화).
 * 질문형 제목 + 3줄요약 + 전개 타임라인 + 인과 + 시나리오 + 종합해석 (opus md).
 * 도시에 2단 패턴: GET 캐시 → stale이면 compute 자동 발화.
 */
interface Narrative {
  status: string
  title: string | null
  narrative: string | null
  created_at: string | null
  stale: boolean
}

export default function NarrativePage() {
  const [sp] = useSearchParams()
  const navigate = useNavigate()
  const topic = sp.get("topic") ?? ""

  const cached = useQuery(
    apiQuery<Narrative>({
      key: ["spine", "narrative", topic],
      url: `/api/spine/narrative?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short, enabled: !!topic,
    }),
  )
  const fresh = useQuery(
    apiComputeQuery<Narrative>({
      key: ["spine", "narrative", topic, "compute"],
      url: `/api/spine/narrative/compute?topic=${encodeURIComponent(topic)}`,
      enabled: !!cached.data?.stale,
    }),
  )
  const n = fresh.data ?? cached.data

  if (!topic) return <ErrorState message="주제가 없습니다 (?topic= 필요)" />
  if (cached.isLoading) return <PageContainer gap="sm"><Skeleton className="h-8 w-96" /><Skeleton className="h-64 w-full rounded-xl" /></PageContainer>

  const generating = fresh.isFetching
  const empty = n?.status === "empty" && !n?.narrative && !generating

  return (
    <PageContainer gap="sm" width="reading">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate("/explore?list=theme_surge")}>
          <ArrowLeft className="h-4 w-4" /> 주목 주제
        </Button>
        <Badge variant="secondary" className="text-[10px]">내러티브</Badge>
      </div>

      {empty ? (
        <EmptyState message={`'${topic}' 관련 문서가 아직 충분하지 않습니다 (3건 이상 필요).`} />
      ) : (
        <>
          <h1 className="text-xl font-bold leading-snug flex items-start gap-2">
            <Sparkles className="h-5 w-5 text-hypothesis shrink-0 mt-0.5" />
            {n?.title ?? topic}
          </h1>
          {generating && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              최근 문서를 엮어 내러티브 생성 중… (수십 초)
            </div>
          )}
          {n?.narrative && (
            <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_6%,var(--card))]">
              <CardContent className="py-4">
                <Markdown>{n.narrative}</Markdown>
                <div className="text-right mt-2">
                  <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                    AI 내러티브 · 문서 집합 변경 시 갱신 — 검증 필요
                    {n.created_at && ` · ${n.created_at.slice(0, 10)}`}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </PageContainer>
  )
}
