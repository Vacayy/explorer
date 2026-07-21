import { Link, useSearchParams } from "react-router-dom"
import { ArrowLeft, FileText } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { PageContainer } from "@/components/shared/PageContainer"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/shared/ErrorState"
import { ReportView } from "@/components/explore/ReportView"

/**
 * /report — 통합 리포트 공간 (월드모델 탭, integrated-report/D-041).
 * topic 없음=발간 목록, ?topic=X=디테일(ReportView, 최하단에 구성 내러티브 링크).
 */
interface ReportListItem {
  anchor_topic: string
  title: string | null
  n_members: number
  n_stocks: number
  created_at: string
}

export default function ReportsPage() {
  const [params] = useSearchParams()
  const topic = params.get("topic")
  return topic ? <ReportDetail topic={topic} /> : <ReportList />
}

function ReportDetail({ topic }: { topic: string }) {
  return (
    <PageContainer>
      <Link to="/report" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-3.5 w-3.5" /> 리포트 목록
      </Link>
      <ReportView topic={topic} />
    </PageContainer>
  )
}

function ReportList() {
  const { data = [], isLoading } = useQuery(
    apiQuery<ReportListItem[]>({
      key: ["spine", "report", "list"],
      url: "/api/spine/report/list",
      staleTime: STALE.short,
    }),
  )
  return (
    <PageContainer>
      <div>
        <h2 className="text-xl font-bold">리포트</h2>
        <p className="text-sm text-muted-foreground">공유 인과로 엮인 내러티브 + 종목 분석을 종합한 Top-down 리포트</p>
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" />
        </div>
      )}

      {!isLoading && data.length === 0 && (
        <EmptyState message="아직 발간된 리포트가 없습니다 — 내러티브 상세의 '통합 리포트'에서 생성하세요." />
      )}

      <div className="space-y-2">
        {data.map((r) => (
          <Link key={r.anchor_topic} to={`/report?topic=${encodeURIComponent(r.anchor_topic)}`} className="block">
            <Card className="hover:border-primary/40 transition-colors">
              <CardContent className="py-3 flex items-start gap-3">
                <FileText className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-sm">{r.title || `${r.anchor_topic} 통합 리포트`}</div>
                  <div className="flex items-center gap-1.5 mt-1 text-[11px] text-muted-foreground">
                    <Badge variant="secondary" className="text-[10px] font-normal">{r.anchor_topic}</Badge>
                    <span>내러티브 {r.n_members} · 종목 {r.n_stocks}</span>
                    <span className="tabular-nums">· {r.created_at.slice(0, 10)}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </PageContainer>
  )
}
