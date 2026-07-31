import { Link } from "react-router-dom"
import { FileText, Inbox, LineChart, Route, Sparkles, Workflow } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { useHome } from "@/hooks/useHome"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from '@/components/shared/PageContainer'
import { ProposalPanel } from "@/components/shared/ProposalPanel"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { NarrativeList } from "@/components/explore/NarrativeList"
import { MomentumSection, ThemeSurgeSummary, GraphActivitySection } from "@/components/home/HomeSignals"
import { MarketRegime } from "@/components/home/MarketRegime"
import { UsBriefingSection } from "@/components/home/UsBriefingSection"

/**
 * /home — 아침 브리핑 + 신호 대시보드 (morning terminal, D-056·D-057).
 * 기계의 3줄 → 승인 배너 → 월드모델 델타(변한 내러티브·최근 리포트, 매일 여는 것) →
 * 신호(언급 모멘텀·주목 주제·인과 활동 — 탐색 해체로 이관).
 * 승인 대기는 헤더 상시 배지가 주 진입 — 여기선 카운트 배너만.
 * 신호 상세 목록은 /explore?list= (pill 없는 도시에).
 */
export default function HomePage() {
  const { data, isLoading, isError, refetch } = useHome()

  if (isLoading) return <HomeSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  return (
    <PageContainer>
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-bold">Home</h2>
        <FreshnessStamp asOf={data.as_of} />
      </div>

      {/* 어젯밤 미국장 브리핑 — 아침 분위기 파악 (자금이 어디로 쏠렸나, D-095) */}
      <UsBriefingSection />

      {/* AI가 최근 만든 것 (지난 7일) — 자동/승인 생성물 최신순 피드. 공지(브리핑)·승인은 인박스로(D-054) */}
      <AiActivityFeed />

      {/* 시장 국면 — 매크로 리스크 포스처 (그날의 렌즈니 델타 위, D-076) */}
      <MarketRegime />

      {/* 월드모델 델타 — 매일 여는 것을 진입 요약으로 (내러티브 + 리포트) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
        <NarrativeDeltaCard />
        <RecentReportsCard />
      </div>

      {/* 신호 대시보드 — 탐색 해체로 Home 흡수 (세로 스택) */}
      <MomentumSection />
      <ThemeSurgeSummary />
      <GraphActivitySection />
    </PageContainer>
  )
}


/* ---------- AI 자동생성 피드 (지난 7일 · 최신순, 승인 대기 칩 통합) ---------- */

interface AiActivityItem {
  type: string; title: string; topic: string; code: string | null; question_id?: number | null; created_at: string
}
const ACT_META: Record<string, { label: string; Icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  narrative: { label: "내러티브", Icon: Sparkles, cls: "text-hypothesis border-hypothesis/40" },
  mega: { label: "메가", Icon: Workflow, cls: "text-hypothesis border-hypothesis/40" },
  report: { label: "리포트", Icon: FileText, cls: "text-primary border-primary/40" },
  scenario: { label: "파급", Icon: Route, cls: "text-muted-foreground" },
  digest: { label: "요약", Icon: LineChart, cls: "text-muted-foreground" },
}
function actLink(a: AiActivityItem): string {
  if (a.type === "report") return `/report?topic=${encodeURIComponent(a.topic)}`
  if (a.type === "digest" && a.code) return `/analyze/${a.code}/summary`
  if (a.type === "mega") return "/narrative"
  if (a.type === "scenario") return a.question_id ? `/question/${a.question_id}` : `/narrative?topic=${encodeURIComponent(a.topic)}`
  return `/narrative?topic=${encodeURIComponent(a.topic)}`
}

function AiActivityFeed() {
  const { data: items = [], isLoading } = useQuery(
    apiQuery<AiActivityItem[]>({ key: ["spine", "home", "ai-activity"], url: "/api/spine/home/ai-activity?days=7", staleTime: STALE.short }),
  )
  const { data: approvals = [] } = useQuery(
    apiQuery<{ id: number }[]>({ key: ["spine", "approvals"], url: "/api/spine/approvals", staleTime: STALE.short }),
  )
  if (isLoading) return <Skeleton className="h-40 w-full rounded-xl" />
  return (
    <ProposalPanel
      icon={Sparkles} title="AI가 최근 만든 것" subtitle="지난 7일 · 최신순" count={items.length}
      maxHeight="46vh" contentClassName="px-0 divide-y"
      action={approvals.length > 0
        ? <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40 gap-1">
            <Inbox className="h-3 w-3" /> 승인 대기 {approvals.length} · 우상단 인박스
          </Badge>
        : undefined}>
      {items.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted-foreground">지난 7일간 자동생성된 콘텐츠가 없습니다.</p>
      ) : items.map((a, i) => {
        const m = ACT_META[a.type] ?? ACT_META.narrative
        return (
          <Link key={`${a.type}-${a.topic}-${i}`} to={actLink(a)}
            className="flex items-center gap-2 px-4 py-1.5 hover:bg-muted/50">
            <m.Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <Badge variant="outline" className={`text-[9px] shrink-0 ${m.cls}`}>{m.label}</Badge>
            <span className="text-sm truncate min-w-0 flex-1">{a.title}</span>
            <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">{a.created_at.slice(5, 16)}</span>
          </Link>
        )
      })}
    </ProposalPanel>
  )
}

/* ---------- 월드모델 델타: 내러티브 ---------- */

function NarrativeDeltaCard() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-hypothesis" /> 내러티브 — 지금 움직이는 주제
          <Link to="/narrative" className="ml-auto text-[11px] font-normal text-muted-foreground hover:text-foreground">전체 →</Link>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <NarrativeList limit={5} empty="state" />
      </CardContent>
    </Card>
  )
}

/* ---------- 월드모델 델타: 최근 리포트 ---------- */

interface ReportListItem {
  anchor_topic: string
  title: string | null
  n_members: number
  n_stocks: number
  created_at: string
}

function RecentReportsCard() {
  const { data = [] } = useQuery(
    apiQuery<ReportListItem[]>({ key: ["spine", "report", "list"], url: "/api/spine/report/list", staleTime: STALE.short }),
  )
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <FileText className="h-4 w-4 text-muted-foreground" /> 최근 리포트
          <Link to="/report" className="ml-auto text-[11px] font-normal text-muted-foreground hover:text-foreground">전체 →</Link>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <EmptyState message="아직 발간된 리포트가 없습니다 — 내러티브 상세에서 생성하세요." />
        ) : (
          <ul className="space-y-2.5">
            {data.slice(0, 5).map((r) => (
              <li key={r.anchor_topic}>
                <Link to={`/report?topic=${encodeURIComponent(r.anchor_topic)}`} className="group flex items-start gap-2">
                  <FileText className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm leading-snug group-hover:underline">{r.title || `${r.anchor_topic} 통합 리포트`}</div>
                    <div className="flex items-center gap-1.5 mt-0.5 text-[11px] text-muted-foreground">
                      <Badge variant="secondary" className="text-[10px] font-normal">{r.anchor_topic}</Badge>
                      <span>내러티브 {r.n_members} · 종목 {r.n_stocks}</span>
                      <span className="tabular-nums">· {r.created_at.slice(0, 10)}</span>
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- Loading skeleton ---------- */

function HomeSkeleton() {
  return (
    <PageContainer>
      <Skeleton className="h-6 w-24" />
      {[80, 160, 180].map((h, i) => (
        <div key={i} className="border rounded-xl p-4 space-y-3">
          <Skeleton className="h-4 w-32" />
          <Skeleton style={{ height: h }} className="w-full" />
        </div>
      ))}
    </PageContainer>
  )
}
