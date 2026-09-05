// /synthesis/:id — 문서 교차 종합 열람 (D-104, docs/specs/doc-synthesis.md)
// 사람이 고른 문서 묶음을 엮어 읽은 산출물. 프레임(가설)이지 판정이 아니다 — read-only.
import { Link, useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, FileText, Layers } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import { Markdown } from "@/components/shared/Markdown"
import { SourceBadge } from "@/components/shared/SourceBadge"
import SaveButton from "@/components/shared/SaveButton"
import { formatRelativeTime } from "@/utils/format"
import { useSynthesis } from "@/hooks/useSynthesis"

/** SQLite datetime('now')는 UTC 공백 포맷 — ISO UTC로 정규화 후 상대시각 */
function when(created_at: string | null): string {
  if (!created_at) return "-"
  return formatRelativeTime(created_at.includes("T") ? created_at : created_at.replace(" ", "T") + "Z")
}

export default function SynthesisPage() {
  const { synthesisId } = useParams<{ synthesisId: string }>()
  const navigate = useNavigate()
  const { data, isLoading, isError, refetch } = useSynthesis(synthesisId)

  if (isLoading) {
    return (
      <PageContainer width="reading" gap="sm">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </PageContainer>
    )
  }
  if (isError || !data) {
    return <ErrorState message="종합을 찾을 수 없습니다." onRetry={() => refetch()} />
  }

  const title = data.title || `문서 ${data.docs.length}건 교차 종합`

  return (
    <PageContainer width="reading" gap="sm">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate("/follow/saved")}
        className="h-auto border-0 p-0 font-normal flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:bg-transparent"
      >
        <ArrowLeft className="size-3.5" /> 저장됨
      </Button>

      <div className="flex items-start gap-2">
        <Layers className="mt-1 h-5 w-5 shrink-0 text-hypothesis" />
        <h1 className="min-w-0 flex-1 text-xl font-bold leading-snug">{title}</h1>
        <SaveButton
          kind="synthesis"
          refId={String(data.id)}
          url={`/synthesis/${data.id}`}
          title={title}
          subtitle={`문서 ${data.docs.length}건 종합`}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">
          교차 프레임 · 가설
        </Badge>
        <span>문서 {data.docs.length}건을 엮음</span>
        <span>· {when(data.created_at)}</span>
      </div>

      <Card>
        <CardContent className="py-4">
          <Markdown>{data.body}</Markdown>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-2 py-4">
          <h2 className="text-[13px] font-semibold">엮은 문서</h2>
          {/* 번호 라벨 없음 — 본문이 번호 대신 자연어로 출처를 밝히므로(D-105) 번호는 가리킬 대상이 없다 */}
          <ul className="divide-y">
            {data.docs.map((d) => (
              <li key={d.id} className="flex items-center gap-2 py-2">
                {d.source_type ? (
                  <SourceBadge sourceType={d.source_type} />
                ) : (
                  <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                )}
                <Link
                  to={`/doc/${d.id}`}
                  className="min-w-0 flex-1 truncate text-sm hover:text-primary hover:underline"
                >
                  {d.title || `문서 #${d.id} (원문 없음)`}
                </Link>
                {d.published_at && (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {d.published_at.slice(0, 10)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
