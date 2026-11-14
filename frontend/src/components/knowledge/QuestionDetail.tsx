import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query"
import { toast } from "sonner"
import { ChevronDown, ChevronLeft, FileText, Loader2 } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import api from "@/api/client"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { Markdown } from "@/components/shared/Markdown"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { PageContainer } from "@/components/shared/PageContainer"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { JudgmentFrame } from "@/components/thesis/JudgmentFrame"
import {
  DIVERGENCE, QUESTION_ORIGIN, QuestionTree, VerdictBadge, type QTree,
} from "@/components/knowledge/QuestionsSection"
import { scenarioSide, splitSynthesis } from "@/lib/judgment"
import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/format"

const mmdd = (iso: string | null | undefined) => (iso ? `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}` : "-")

/**
 * /question/:id — 질문 허브 (D-070 교통정리, ia-redesign §4.27 A · 시안 Question-Detail). 한 소스/질문의 산출물을 한 화면에:
 * 머리(질문 · 2층 판정 · 출처) → 판정 요약 → 넓은 화면 2단: 분할정복 트리(서브질문 · 프록시 · 관측 건수) | 질문 종합(낡음 줄 맨 위,
 * '아직 미판정·흔들릴 조건' 접음) · 파급 시나리오(논리상 수혜·피해 — 인과 추론, 판정 아님). 블록 단위 실패.
 */
export default function QuestionDetail() {
  const { id } = useParams<{ id: string }>()
  const qid = Number(id)
  const tree = useQuery(
    apiQuery<QTree>({ key: ["spine", "questions", qid], url: `/api/spine/questions/${qid}`, staleTime: STALE.short }),
  )
  const data = tree.data
  const div = data?.divergence && DIVERGENCE[data.divergence]
  const origin = data?.created_by ? QUESTION_ORIGIN[data.created_by] : null

  return (
    <PageContainer gap="sm">
      <JudgmentFrame actions={
        <Link to="/questions" className="inline-flex items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-3.5" /> 미결 질문
        </Link>} />

      {tree.isPending ? (
        <div className="space-y-2"><Skeleton className="h-7 w-full max-w-2xl" /><Skeleton className="h-5 w-64" /></div>
      ) : data ? (
        <div className="flex flex-col gap-2">
          <h2 className="text-xl font-bold leading-snug">{data.text}</h2>
          <div className="flex flex-wrap items-center gap-1.5">
            <VerdictBadge v={data.confirm_verdict} prefix="확정 " />
            <VerdictBadge v={data.lead_verdict} prefix="선행 " />
            {origin && <Badge variant="outline" className={cn("text-[10px]", origin.cls)}>{origin.label}</Badge>}
            {div && <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">{div}</Badge>}
            <span className="text-[11px] tabular-nums text-muted-foreground">
              추적 시작 {mmdd(data.created_at)} · 판정 갱신 {mmdd(data.updated_at)}
            </span>
            {data.source_doc && (
              <Link to={`/doc/${data.source_doc.id}`} className="ml-auto">
                <Badge variant="outline" className="text-[10px] gap-1 hover:border-primary">
                  <FileText className="h-3 w-3" /> 출처 소스
                </Badge>
              </Link>
            )}
          </div>
          {data.verdict_summary && (
            <p className="text-[13px] text-muted-foreground bg-muted/40 px-3 py-2">{data.verdict_summary}</p>
          )}
        </div>
      ) : <h2 className="text-xl font-bold">질문 #{qid}</h2>}

      <div className="surface-grid grid grid-cols-1 items-start lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <TreeBlock qid={qid} tree={tree} />
        <div className="surface-stack flex flex-col">
          <SynthesisBlock qid={qid} />
          {data && <ScenarioBlock qid={qid} data={data} />}
        </div>
      </div>
    </PageContainer>
  )
}

/* ---------- 분할정복 트리 ---------- */
function TreeBlock({ qid, tree }: { qid: number; tree: UseQueryResult<QTree> }) {
  const d = tree.data
  const proxies = d?.sub_questions.flatMap((s) => s.proxies) ?? []
  const obs = proxies.reduce((n, p) => n + (p.obs_count ?? p.observations.length), 0)
  const waiting = proxies.filter((p) => (p.obs_count ?? p.observations.length) === 0).length
  return (
    <Card className="py-0">
      <CardContent className="space-y-2 py-4">
        <h3 className="flex flex-wrap items-baseline gap-x-2 text-[15px] font-semibold">
          분할정복 — 서브질문 · 프록시 · 관측
          {d && <span className="text-[11px] font-normal tabular-nums text-muted-foreground">
            서브질문 {d.sub_questions.length} · 프록시 {proxies.length} · 관측 {formatNumber(obs)}건{waiting > 0 && ` · 관측 대기 ${waiting}`}
          </span>}
        </h3>
        {tree.isPending ? <Skeleton className="h-64 w-full rounded-card" />
          : tree.isError ? <ErrorState message="질문을 찾을 수 없습니다." onRetry={() => void tree.refetch()} />
          : d && d.sub_questions.length === 0 ? <p className="py-2 text-sm text-muted-foreground">분해 중입니다.</p>
          : <QuestionTree id={qid} />}
      </CardContent>
    </Card>
  )
}

/* ---------- 질문 종합 — 현재 결산 (D-093) ---------- */
function SynthesisBlock({ qid }: { qid: number }) {
  const qc = useQueryClient()
  // 질문 종합 (D-093) — 현재 결산 리포트 (LLM 0 캐시 + stale)
  const synth = useQuery(
    apiQuery<{ status: string; body: string | null; created_at: string | null; stale: boolean }>(
      { key: ["spine", "questions", qid, "synthesis"], url: `/api/spine/questions/${qid}/synthesis`, staleTime: STALE.short }),
  )
  // 체인: 리포트(sonnet) → 그걸 출발 조건으로 파급 시나리오(opus). 트리 키 무효화로 둘 다 갱신. 낡아도 자동으로 다시 만들지 않는다(11-04 결정 ②)
  const genSynth = useMutation({
    mutationFn: () => api.post(`/api/spine/questions/${qid}/synthesis/compute`),
    onSuccess: () => { toast.success("질문 종합을 만들었습니다(결산 → 파급 시나리오)."); qc.invalidateQueries({ queryKey: ["spine", "questions", qid] }) },
    onError: () => toast.error("종합을 만들지 못했습니다. 이전 결산은 그대로입니다."),
  })
  const body = synth.data?.body ?? null
  const { main, folded } = body ? splitSynthesis(body) : { main: "", folded: "" }
  const genButton = (label: string) => (
    <Button size="sm" variant="outline" disabled={genSynth.isPending} onClick={() => genSynth.mutate()}>
      {genSynth.isPending ? <><Loader2 className="h-3 w-3 animate-spin" /> 종합 중… (수 분)</> : label}
    </Button>
  )
  return (
    <Card className="py-0">
      <CardContent className="space-y-3 py-4">
        <div className="flex items-center gap-1">
          <h3 className="text-[15px] font-semibold">질문 종합 — 현재 결산</h3>
          <InfoTip label="질문 종합 설명">지금까지 추적한 서브질문·판정·근거로 답할 수 있는 것을 짧게 결산하고, 이어서 그 결산을 출발 조건으로 파급 시나리오를 만듭니다.</InfoTip>
          {body && !synth.data?.stale && <span className="ml-auto">{genButton("다시 종합")}</span>}
        </div>
        {synth.isPending ? <Skeleton className="h-40 w-full rounded-card" />
          : synth.isError ? <ErrorState message="질문 종합을 불러오지 못했습니다." onRetry={() => void synth.refetch()} />
          : !body ? <div>{genButton("종합 생성")}</div>
          : <>
            {synth.data?.stale && (
              <div className="flex flex-wrap items-center justify-between gap-2 bg-[color-mix(in_srgb,var(--chart-warning)_12%,var(--card))] px-3 py-2 text-[13px]" data-stale="synthesis">
                <span>{mmdd(synth.data.created_at)}에 만든 결산입니다. 그 뒤 관측이 갱신됐습니다.</span>
                {genButton("다시 종합")}
              </div>
            )}
            <div className="text-sm"><Markdown>{main}</Markdown></div>
            {folded && (
              <Collapsible>
                <CollapsibleTrigger className="group flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">
                  <ChevronDown className="size-3.5 transition-transform group-data-[state=closed]:-rotate-90" />
                  아직 미판정 · 흔들릴 조건
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-2 text-sm"><Markdown>{folded}</Markdown></CollapsibleContent>
              </Collapsible>
            )}
          </>}
      </CardContent>
    </Card>
  )
}

/* ---------- 파급 시나리오 — 결산을 출발 조건으로 한 전방 전망 ---------- */
function ScenarioBlock({ qid, data }: { qid: number; data: QTree }) {
  const qc = useQueryClient()
  const genScenario = useMutation({
    mutationFn: () => api.post(`/api/spine/questions/${qid}/scenario`, { event: data.text ?? "" }),
    onSuccess: () => { toast.success("파급 시나리오를 만들었습니다."); qc.invalidateQueries({ queryKey: ["spine", "questions", qid] }) },
    onError: () => toast.error("시나리오를 만들지 못했습니다. 다시 시도해 주세요."),
  })
  const sc = data.scenario
  const sides = (sc?.beneficiaries ?? []).filter((b) => b.name)
  return (
    <Card className="py-0">
      <CardContent className="space-y-3 py-4">
        <div className="flex items-baseline gap-2">
          <h3 className="text-[15px] font-semibold">파급 시나리오</h3>
          {sc && <span className="text-[11px] tabular-nums text-muted-foreground">{mmdd(sc.created_at)}</span>}
          {!sc && (
            <Button size="sm" variant="outline" className="ml-auto" disabled={genScenario.isPending} onClick={() => genScenario.mutate()}>
              {genScenario.isPending ? <><Loader2 className="h-3 w-3 animate-spin" /> 전개 중… (수 분)</> : "시나리오 생성"}
            </Button>
          )}
        </div>
        {sc && (
          <>
            {sides.length > 0 && (
              <div className="space-y-1.5">
                <span className="flex items-center gap-0.5 text-[11px] text-muted-foreground">
                  논리상 수혜·피해 쪽
                  <InfoTip label="수혜·피해 설명">파급 논리로 짚은 인과 추론입니다. 판정이나 매매 권유가 아닙니다.</InfoTip>
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {sides.map((b, i) => {
                    const side = scenarioSide(b.rel)
                    const chip = (
                      <span className="inline-flex items-center gap-1.5 border px-2 py-0.5 text-[12px]" title={b.reason ?? ""}>
                        {b.name}
                        {side && <span className={side === "수혜" ? "text-up-ink" : "text-down-ink"}>{side}</span>}
                      </span>
                    )
                    return b.stock_code ? <Link key={i} to={`/analyze/${b.stock_code}/summary`} className="hover:bg-muted">{chip}</Link> : <span key={i}>{chip}</span>
                  })}
                </div>
              </div>
            )}
            <Collapsible>
              <CollapsibleTrigger className="group flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">
                <ChevronDown className="size-3.5 transition-transform group-data-[state=closed]:-rotate-90" />
                시나리오 전문 보기
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-2 text-sm"><Markdown>{sc.answer}</Markdown></CollapsibleContent>
            </Collapsible>
          </>
        )}
        {data.source_doc && (
          <div className="flex items-center gap-1.5 pt-1 text-[11px] text-muted-foreground">
            <SourceBadge sourceType={data.source_doc.source_type} />
            <Link to={`/doc/${data.source_doc.id}`} className="truncate hover:underline">{data.source_doc.title || "출처 문서"}</Link>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
