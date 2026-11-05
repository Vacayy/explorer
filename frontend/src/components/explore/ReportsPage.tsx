import { Link, useSearchParams } from "react-router-dom"
import { ChevronLeft } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { PageContainer } from "@/components/shared/PageContainer"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { ReportView } from "@/components/explore/ReportView"
import { JudgmentFrame } from "@/components/thesis/JudgmentFrame"
import { cn } from "@/lib/utils"

/**
 * /report — 통합 리포트 공간 (Thesis › 내 판단 › 리포트, integrated-report/D-041 · ia-redesign §4.27 C · 시안 Report).
 * 넓은 화면은 목록 | 상세 한 화면 2단(?topic= 없으면 가장 최근 리포트를 연다). 좁은 화면은 ?topic= 이면 상세만(‹ 리포트 목록), 없으면 목록만.
 * '최근 리포트 n일 전' 경고는 두지 않는다(11-04 기각) — 낡음은 상세의 '작성 이후' 줄로 보인다.
 */
interface ReportListItem {
  anchor_topic: string
  title: string | null
  n_members: number
  n_stocks: number
  created_at: string
}

const mmdd = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`
const md = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`

export default function ReportsPage() {
  const [params] = useSearchParams()
  const topic = params.get("topic")
  const v = params.get("v")
  const list = useQuery(
    apiQuery<ReportListItem[]>({ key: ["spine", "report", "list"], url: "/api/spine/report/list", staleTime: STALE.short }),
  )
  const data = list.data ?? []
  const shown = topic ?? data[0]?.anchor_topic ?? null
  const dates = data.map((r) => r.created_at.slice(0, 10)).sort()

  return (
    <PageContainer gap="sm">
      <JudgmentFrame />
      <div className="surface-grid grid grid-cols-1 items-start lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card className={cn("py-0", topic && "max-lg:hidden")}>
          <CardContent className="space-y-2 py-4">
            <h2 className="flex flex-wrap items-center gap-x-2 text-[15px] font-semibold">
              리포트
              {data.length > 0 && (
                <span className="text-[11px] font-normal tabular-nums text-muted-foreground">
                  {data.length}건 · {dates[0] === dates[dates.length - 1] ? md(dates[0]) : `${md(dates[0])}~${md(dates[dates.length - 1])}`} 발간
                </span>
              )}
              <InfoTip label="리포트 설명">공유 인과로 엮인 내러티브와 종목 분석을 종합한 Top-down 리포트입니다. 내러티브 상세의 '통합 리포트'에서 만듭니다.</InfoTip>
            </h2>
            {list.isPending ? (
              <div className="space-y-2"><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div>
            ) : list.isError ? <ErrorState message="리포트 목록을 불러오지 못했습니다." onRetry={() => void list.refetch()} />
              : data.length === 0 ? <p className="py-2 text-sm text-muted-foreground">아직 발간된 리포트가 없습니다. 내러티브 상세의 '통합 리포트'에서 만듭니다.</p>
              : (
                <ul className="flex flex-col gap-1" aria-label="리포트 목록">
                  {data.map((r) => {
                    const sel = r.anchor_topic === shown
                    return (
                      <li key={r.anchor_topic}>
                        <Link to={`/report?topic=${encodeURIComponent(r.anchor_topic)}`} aria-current={sel ? "true" : undefined}
                          className={cn("flex flex-col gap-1.5 px-3 py-2 hover:bg-muted/50", sel && "border bg-muted/60")}>
                          <span className="line-clamp-2 text-sm">{r.title || `${r.anchor_topic} 통합 리포트`}</span>
                          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            <Badge variant="secondary" className="text-[10px] font-normal">{r.anchor_topic}</Badge>
                            <span className="tabular-nums">내러티브 {r.n_members} · 종목 {r.n_stocks} · {mmdd(r.created_at)}</span>
                          </span>
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              )}
          </CardContent>
        </Card>
        <div className={cn("min-w-0", !topic && "max-lg:hidden")}>
          {topic && (
            <Link to="/report" className="mb-2 inline-flex items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground lg:hidden">
              <ChevronLeft className="size-3.5" /> 리포트 목록
            </Link>
          )}
          {shown ? <ReportView key={`${shown}:${v ?? ""}`} topic={shown} initialVersionId={topic && v ? Number(v) : null} />
            : list.isPending ? <Skeleton className="h-96 w-full rounded-card max-lg:hidden" /> : null}
        </div>
      </div>
    </PageContainer>
  )
}
