import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ArrowLeft, ClipboardList, FileText, HelpCircle, Loader2, Route } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import api from "@/api/client"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Markdown } from "@/components/shared/Markdown"
import { ErrorState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import { SourceBadge } from "@/components/shared/SourceBadge"
import {
  DIVERGENCE, QuestionTree, VerdictBadge, type QTree,
} from "@/components/knowledge/QuestionsSection"

/**
 * /question/:id — 질문 허브 (D-070 교통정리). 한 소스/질문의 산출물을 한 화면에:
 * 2층 판정 + 분할정복 트리 + 파급 시나리오 + 소스 문서. Q5·자동도출·주입 질문 공용.
 */
export default function QuestionDetail() {
  const { id } = useParams<{ id: string }>()
  const qid = Number(id)
  const qc = useQueryClient()
  const navigate = useNavigate()

  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<QTree>({ key: ["spine", "questions", qid], url: `/api/spine/questions/${qid}`, staleTime: STALE.short }),
  )

  const genScenario = useMutation({
    mutationFn: () => api.post(`/api/spine/questions/${qid}/scenario`, { event: data?.text ?? "" }),
    onSuccess: () => { toast.success("파급 시나리오 생성됨"); qc.invalidateQueries({ queryKey: ["spine", "questions", qid] }) },
    onError: () => toast.error("시나리오 생성 실패 — 다시 시도"),
  })

  // 질문 종합 (D-093) — 현재 결산 리포트 (LLM 0 캐시 + stale)
  const synth = useQuery(
    apiQuery<{ status: string; body: string | null; created_at: string | null; stale: boolean }>(
      { key: ["spine", "questions", qid, "synthesis"], url: `/api/spine/questions/${qid}/synthesis`, staleTime: STALE.short }),
  )
  // 체인: 리포트(sonnet) → 그걸 출발 조건으로 파급 시나리오(opus). 트리 키 무효화로 둘 다 갱신.
  const genSynth = useMutation({
    mutationFn: () => api.post(`/api/spine/questions/${qid}/synthesis/compute`),
    onSuccess: () => { toast.success("질문 종합 생성됨 (결산 → 파급 시나리오)"); qc.invalidateQueries({ queryKey: ["spine", "questions", qid] }) },
    onError: () => toast.error("종합 생성 실패 — 다시 시도"),
  })

  if (isLoading) {
    return <PageContainer width="reading" gap="sm"><Skeleton className="h-8 w-96" /><Skeleton className="h-64 w-full rounded-xl" /></PageContainer>
  }
  if (isError || !data) return <ErrorState message="질문을 찾을 수 없습니다." onRetry={() => refetch()} />

  const div = data.divergence && DIVERGENCE[data.divergence]

  return (
    <PageContainer width="reading" gap="sm">
      <Button variant="ghost" size="sm" onClick={() => navigate("/questions")}
        className="h-auto border-0 p-0 font-normal flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:bg-transparent">
        <ArrowLeft className="size-3.5" /> 미결 질문
      </Button>

      <h1 className="text-xl font-bold leading-snug flex items-start gap-2">
        <HelpCircle className="h-5 w-5 text-hypothesis shrink-0 mt-0.5" /> {data.text}
      </h1>

      <div className="flex flex-wrap items-center gap-1.5">
        <VerdictBadge v={data.confirm_verdict} prefix="확정 " />
        <VerdictBadge v={data.lead_verdict} prefix="선행 " />
        {div && <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">{div}</Badge>}
        {data.source_doc && (
          <Link to={`/doc/${data.source_doc.id}`} className="ml-auto">
            <Badge variant="outline" className="text-[10px] gap-1 hover:border-primary">
              <FileText className="h-3 w-3" /> 출처 소스
            </Badge>
          </Link>
        )}
      </div>

      {data.verdict_summary && (
        <p className="text-[13px] text-muted-foreground rounded-md bg-muted/40 px-3 py-2">{data.verdict_summary}</p>
      )}

      {/* 분할정복 트리 */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1">분할정복 — 서브질문 · 프록시 · 관측</p>
        <QuestionTree id={qid} />
      </div>

      {/* 질문 종합 — 현재 결산 리포트 (D-093). 아래 파급 시나리오와 체인(결산 → 전방 전망) */}
      <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_6%,var(--card))]">
        <CardContent className="py-3 space-y-2">
          <div className="flex items-center gap-1.5">
            <ClipboardList className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">질문 종합 — 현재 결산</span>
            <span className="text-[11px] text-muted-foreground">지금까지 추적한 근거로 답할 수 있는 것</span>
            <Button size="xs" variant="outline" className="ml-auto" disabled={genSynth.isPending}
              onClick={() => genSynth.mutate()}>
              {genSynth.isPending
                ? <><Loader2 className="h-3 w-3 animate-spin" /> 종합 중… (수 분)</>
                : (synth.data?.body ? "다시 종합" : "종합 생성")}
            </Button>
          </div>
          {genSynth.isPending && (
            <p className="text-[11px] text-muted-foreground">결산 리포트 → 그걸 출발 조건으로 파급 시나리오까지 이어서 생성합니다.</p>
          )}
          {synth.data?.body ? (
            <div className="rounded-md border bg-card/60 px-3 py-2">
              <Markdown>{synth.data.body}</Markdown>
              {synth.data.stale && !genSynth.isPending && (
                <p className="text-[10px] text-hypothesis mt-1.5">관측이 갱신됐습니다 — '다시 종합'으로 최신화</p>
              )}
            </div>
          ) : !genSynth.isPending && (
            <p className="text-[11px] text-muted-foreground/60">아직 없음 — 서브질문·판정·근거를 종합해 짧은 결산을 만들고, 이어서 파급 시나리오까지 생성합니다.</p>
          )}
        </CardContent>
      </Card>

      {/* 파급 시나리오 (허브: 같은 질문에 묶임) — 위 결산을 출발 조건으로 한 전방 전망 */}
      <Card>
        <CardContent className="py-3 space-y-2">
          <div className="flex items-center gap-1.5">
            <Route className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">파급 시나리오</span>
            <span className="text-[11px] text-muted-foreground">결산을 출발 조건으로 한 1·2·3차 파급 전망</span>
            {!data.scenario && (
              <Button size="xs" variant="outline" className="ml-auto" disabled={genScenario.isPending}
                onClick={() => genScenario.mutate()}>
                {genScenario.isPending
                  ? <><Loader2 className="h-3 w-3 animate-spin" /> 전개 중… (수 분)</>
                  : <>시나리오 생성</>}
              </Button>
            )}
          </div>
          {data.scenario ? (
            <div className="rounded-md border bg-muted/30 px-3 py-2">
              <Markdown>{data.scenario.answer}</Markdown>
              {data.scenario.beneficiaries.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t">
                  <span className="text-[10px] text-muted-foreground mr-1">논리상 수혜:</span>
                  {data.scenario.beneficiaries.map((b, i) => (
                    <Badge key={i} variant="outline" className="text-[10px]" title={b.reason ?? ""}>{b.name ?? "?"}</Badge>
                  ))}
                </div>
              )}
            </div>
          ) : !genScenario.isPending && (
            <p className="text-[11px] text-muted-foreground/60">아직 없음 — 생성하면 이 질문 아래 함께 보관됩니다.</p>
          )}
          {data.source_doc && (
            <div className="text-[11px] text-muted-foreground flex items-center gap-1.5 pt-1">
              <SourceBadge sourceType={data.source_doc.source_type} />
              <Link to={`/doc/${data.source_doc.id}`} className="hover:underline truncate">
                {data.source_doc.title || "출처 문서"}
              </Link>
            </div>
          )}
        </CardContent>
      </Card>
    </PageContainer>
  )
}
