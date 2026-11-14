import { useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ChevronDown, Gauge, Loader2, Sparkles, Telescope, TrendingUp } from "lucide-react"
import api from "@/api/client"
import { PageContainer } from "@/components/shared/PageContainer"
import { JudgmentFrame } from "@/components/thesis/JudgmentFrame"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { useRunThesisAudit, useThesisAudits, useThesisAudit } from "@/hooks/useThesisAudit"
import { cn } from "@/lib/utils"
import type { ThesisAudit, ThesisAuditListItem, ThesisClaim, ThesisEdge, ThesisPendulum, ThesisQuadrant, ThesisVerdict } from "@/types"

const mmdd = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`

/**
 * /thesis — 논지 감사 (thesis audit, docs/private/specs/thesis-audit.md · ia-redesign §4.27 B · 시안 Thesis-Audit).
 * 내 thesis를 축적된 인과그래프에 **대질**(read-only 감사, 등재 아님) — 일치/충돌/반박/신규 델타.
 * moat는 추론이 아니라 정박: 모든 판정이 코퍼스 근거(엣지·독립 소스·시점)를 가리킨다.
 * 넓은 화면 2단: 왼쪽 새 논지 감사(작은 입력) · 감사 기록 | 오른쪽 감사 결과(감사한 원문 접음 → 판정·진자 분포 → 주장 카드).
 * 보는 감사는 주소 ?audit=<id>(없으면 가장 최근 기록).
 */
export default function ThesisAuditPage() {
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()
  const [text, setText] = useState("")
  const run = useRunThesisAudit()
  const history = useThesisAudits()
  const picked = Number(params.get("audit")) || null
  const viewId = picked ?? history.data?.[0]?.id ?? null
  const loaded = useThesisAudit(run.isPending ? null : viewId)

  function submit(body: string) {
    run.mutate(body.trim(), {
      onSuccess: (a) => {
        qc.invalidateQueries({ queryKey: ["spine", "thesis", "audits"] })
        qc.setQueryData(["spine", "thesis", a.id], a)
        setParams((p) => { const n = new URLSearchParams(p); n.set("audit", String(a.id)); return n })
        setText("")
      },
      onError: () => toast.error("감사를 마치지 못했습니다. 다시 시도해 주세요."),
    })
  }
  const open = (id: number) => setParams((p) => { const n = new URLSearchParams(p); n.set("audit", String(id)); return n })

  return (
    <PageContainer gap="sm">
      <JudgmentFrame />
      <div className="surface-grid grid grid-cols-1 items-start lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="surface-stack flex flex-col">
          <Card className="py-0">
            <CardContent className="space-y-2 py-4">
              <h2 className="flex items-center gap-1 text-[15px] font-semibold">
                새 논지 감사
                <InfoTip label="논지 감사 설명">내 투자 논지를 여러 주장으로 나눠 각각을 그래프의 인과 엣지·독립 소스·시간 급증에 대질합니다. 읽기 전용이라 그래프에 등재하지 않습니다.</InfoTip>
              </h2>
              <Textarea rows={5} value={text} onChange={(e) => setText(e.target.value)}
                placeholder="투자 논지를 붙여넣으세요. 여러 주장으로 나눠 각각을 그래프의 인과 엣지·독립 소스·시간 급증에 대질합니다." />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Button size="sm" onClick={() => submit(text)} disabled={run.isPending || text.trim().length < 10}>
                  {run.isPending ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 감사 중…</> : "감사 실행"}
                </Button>
                <span className="text-[11px] text-muted-foreground">분해 → 정박 → 판정 · 수 분</span>
              </div>
            </CardContent>
          </Card>
          <HistoryList query={history} onOpen={open} activeId={run.isPending ? null : viewId} />
        </div>
        <div className="min-w-0">
          {run.isPending ? <AuditSkeleton label="감사 중입니다 — 분해 → 정박 → 판정, 수 분 걸립니다." />
            : viewId == null ? (history.isPending ? <AuditSkeleton /> : null)
            : loaded.isPending ? <AuditSkeleton />
            : loaded.isError ? <ErrorState message="감사 결과를 불러오지 못했습니다." onRetry={() => void loaded.refetch()} />
            : loaded.data ? <AuditResult audit={loaded.data} onRerun={() => submit(loaded.data!.thesis_text)} rerunning={run.isPending} /> : null}
        </div>
      </div>
    </PageContainer>
  )
}

/* ── 판정 시맨틱 ── */
const VERDICT: Record<ThesisVerdict, { label: string; color: string }> = {
  aligned: { label: "일치", color: "var(--color-chart-green)" },
  contested: { label: "충돌", color: "var(--color-chart-warning)" },
  challenged: { label: "반박", color: "var(--color-chart-negative)" },
  novel: { label: "신규", color: "var(--color-muted-foreground)" },
}
const ROLE: Record<string, string> = {
  consensus: "합의", shift: "변화", catalyst: "촉매", causal: "인과", synthesis: "종합",
}
const STANCE: Record<string, { label: string; color: string }> = {
  support: { label: "지지", color: "var(--color-chart-green)" },
  contradict: { label: "반박", color: "var(--color-chart-negative)" },
  context: { label: "배경", color: "var(--color-muted-foreground)" },
}
/* 진자 (stage 3) — verdict와 직교 축: 선반영 vs 소외 기회. 소외가 상금, 선반영이 경고. */
const QUADRANT: Record<ThesisQuadrant, { label: string; hint: string; color: string }> = {
  hidden_edge: { label: "소외 기회", hint: "주목↓·확신↑ — 아직 안 회자된 정박 논지", color: "var(--color-chart-green)" },
  priced_in: { label: "선반영", hint: "주목↑·확신↑ — 시장도 이미 안다, 엣지 소진", color: "var(--color-chart-warning)" },
  overhyped: { label: "과열", hint: "주목↑·확신↓ — 회자되나 근거 얇음", color: "var(--color-chart-negative)" },
  noise: { label: "노이즈", hint: "주목↓·확신↓ — 근거·관심 모두 약함", color: "var(--color-muted-foreground)" },
}

function AuditResult({ audit, onRerun, rerunning }: { audit: ThesisAudit; onRerun: () => void; rerunning: boolean }) {
  const counts = audit.claims.reduce<Record<string, number>>((a, c) => {
    a[c.verdict] = (a[c.verdict] ?? 0) + 1; return a
  }, {})
  const qCounts = audit.claims.reduce<Record<string, number>>((a, c) => {
    if (c.pendulum) a[c.pendulum.quadrant] = (a[c.pendulum.quadrant] ?? 0) + 1; return a
  }, {})
  const hasPendulum = audit.claims.some((c) => c.pendulum)
  const verdicts = (["aligned", "contested", "challenged", "novel"] as ThesisVerdict[]).filter((v) => counts[v])
  const firstLine = audit.thesis_text.trim().split("\n")[0].slice(0, 60)
  return (
    <Card className="py-0">
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex flex-wrap items-baseline gap-x-2 text-[15px] font-semibold">
            감사 결과
            <span className="text-[11px] font-normal tabular-nums text-muted-foreground">
              {mmdd(audit.created_at)} 감사 · 주장 {audit.n_claims} — {verdicts.map((v) => `${VERDICT[v].label} ${counts[v]}`).join(" · ")}
            </span>
          </h2>
          <Button size="sm" variant="outline" disabled={rerunning} onClick={onRerun}>이 논지 다시 감사</Button>
        </div>

        {/* 감사한 원문 — 기록을 열어도 무엇을 감사했는지 보이게(§4.27 B 제안) */}
        <Collapsible className="bg-muted/40 px-3 py-2">
          <CollapsibleTrigger className="group flex w-full min-w-0 items-center gap-1 text-left text-[13px]">
            <ChevronDown className="size-3.5 shrink-0 transition-transform group-data-[state=closed]:-rotate-90" />
            <span className="shrink-0">감사한 논지 원문</span>
            <span className="min-w-0 truncate text-muted-foreground">· {firstLine}</span>
          </CollapsibleTrigger>
          <CollapsibleContent className="whitespace-pre-wrap pt-2 text-[13px] leading-relaxed">{audit.thesis_text}</CollapsibleContent>
        </Collapsible>

        {/* 진자 분포 (선반영/소외 기회) — 값이 없는 감사는 그렇다고 드러낸다 */}
        <div className="flex flex-wrap items-center gap-2 text-xs" data-pendulum={hasPendulum ? "some" : "none"}>
          <span className="text-muted-foreground">선반영 · 소외 기회(진자)</span>
          {hasPendulum ? (["hidden_edge", "priced_in", "overhyped", "noise"] as ThesisQuadrant[]).filter((q) => qCounts[q]).map((q) => (
            <span key={q} className="inline-flex items-center gap-1" style={{ color: QUADRANT[q].color }}>
              <Gauge className="h-3 w-3" />{QUADRANT[q].label} {qCounts[q]}
            </span>
          )) : <span className="text-muted-foreground">· 이 감사엔 값 없음</span>}
        </div>
        <div className="divide-y border-t">
          {audit.claims.map((c, i) => <ClaimCard key={i} claim={c} />)}
        </div>
      </CardContent>
    </Card>
  )
}

function ClaimCard({ claim }: { claim: ThesisClaim }) {
  const v = VERDICT[claim.verdict]
  const rel = claim.edges.filter((e) => e.stance !== "context").slice(0, 4)
  const ctx = claim.edges.filter((e) => e.stance === "context").slice(0, 2)
  return (
    <div className="space-y-2 py-3">
        <div className="flex items-start gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full shrink-0 mt-1.5" style={{ background: v.color }} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <Badge variant="outline" className="text-[9px] font-normal">{ROLE[claim.role] ?? claim.role}</Badge>
              <span className="text-sm font-medium" style={{ color: v.color }}>{v.label}</span>
              {claim.spiking && (
                <Badge variant="outline" className="text-[9px] gap-0.5 text-[var(--color-chart-warning)] border-[var(--color-chart-warning)]/40">
                  <TrendingUp className="h-2.5 w-2.5" /> 최근 급증
                </Badge>
              )}
            </div>
            <p className="text-sm mt-1 leading-snug">{claim.claim}</p>
          </div>
          <PromoteButton text={claim.claim} />
        </div>

        {/* 진자 (stage 3) — 선반영 vs 소외 기회 */}
        {claim.pendulum && <PendulumRow p={claim.pendulum} />}

        {/* 근거 엣지 (정박 — moat) */}
        {rel.length > 0 && (
          <ul className="space-y-1 pl-4">
            {rel.map((e) => <EdgeRow key={e.id} e={e} />)}
          </ul>
        )}
        {ctx.length > 0 && (
          <ul className="space-y-1 pl-4 opacity-70">
            {ctx.map((e) => <EdgeRow key={e.id} e={e} />)}
          </ul>
        )}

        {/* 내러티브 정박 */}
        {claim.narratives.length > 0 && (
          <div className="pl-4 flex flex-wrap gap-1.5">
            {claim.narratives.slice(0, 3).map((n, i) => (
              <span key={i} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                <Sparkles className="h-3 w-3 text-hypothesis" />
                {(n.title || n.topic).slice(0, 34)} <span className="opacity-60">v{n.version}</span>
              </span>
            ))}
          </div>
        )}

        {claim.edges.length === 0 && claim.narratives.length === 0 && (
          <p className="pl-4 text-[11px] text-muted-foreground">그래프에 근거 없음 — 앞서거나 코퍼스가 얇음</p>
        )}
    </div>
  )
}

function EdgeRow({ e }: { e: ThesisEdge }) {
  const s = STANCE[e.stance] ?? STANCE.context
  const dir = e.effect_direction === "positive" ? "+" : e.effect_direction === "negative" ? "−" : ""
  return (
    <li className="text-[11px] flex items-start gap-1.5">
      <span className="font-medium shrink-0" style={{ color: s.color }}>{s.label}</span>
      <span className="text-muted-foreground shrink-0 tabular-nums">
        [{e.corroborated_by}독립{dir && `·${dir}`}]
      </span>
      <span className="min-w-0">
        <span className="text-foreground">{e.src} → {e.dst}</span>
        {e.mechanism && <span className="text-muted-foreground"> · {e.mechanism.slice(0, 46)}</span>}
      </span>
    </li>
  )
}

/* 승격 (#2) — 감사된 주장을 추적 질문으로. decompose_question 재사용(서브질문·반증조건·프록시 스폰).
   격리 유지: created_by='user'(격리 태그), 질문은 독립 테이블 — 그래프 무변경. */
function PromoteButton({ text }: { text: string }) {
  const navigate = useNavigate()
  const promote = useMutation({
    mutationFn: async () => (await api.post("/api/spine/questions", { text, created_by: "thesis" })).data as { id: number },
    onSuccess: (q) => { toast.success("추적 질문으로 승격 — 상세로 이동"); navigate(`/question/${q.id}`) },
    onError: () => toast.error("승격 실패 — 다시 시도"),
  })
  return (
    <Button variant="ghost" size="sm"
      className="h-6 shrink-0 px-2 text-[11px] text-hypothesis hover:bg-hypothesis/5"
      disabled={promote.isPending} onClick={() => promote.mutate()}
      title="이 주장을 추적 질문으로 승격 — 프록시·2층 판정·반증 감시를 얻습니다">
      {promote.isPending
        ? <Loader2 className="h-3 w-3 animate-spin" />
        : <Telescope className="h-3 w-3" />}
      추적 시작
    </Button>
  )
}

function PendulumRow({ p }: { p: ThesisPendulum }) {
  const q = QUADRANT[p.quadrant as ThesisQuadrant] ?? QUADRANT.noise
  return (
    <div className="pl-4 flex items-center gap-2 text-[11px] flex-wrap">
      <Badge variant="outline" className="text-[9px] gap-1" style={{ color: q.color, borderColor: `${q.color}66` }} title={q.hint}>
        <Gauge className="h-2.5 w-2.5" /> {q.label}
      </Badge>
      <PBar label="주목" value={p.salience} />
      <PBar label="확신" value={p.conviction} />
    </div>
  )
}

function PBar({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1 shrink-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="inline-block h-1.5 w-10 rounded-full bg-muted overflow-hidden align-middle">
        <span className="block h-full rounded-full"
          style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`, background: "var(--color-foreground)" }} />
      </span>
    </span>
  )
}

function HistoryList({ query, onOpen, activeId }: {
  query: ReturnType<typeof useThesisAudits>; onOpen: (id: number) => void; activeId: number | null
}) {
  const data: ThesisAuditListItem[] = query.data ?? []
  return (
    <Card className="py-0">
      <CardContent className="space-y-2 py-4">
        <h2 className="flex items-center gap-1 text-[15px] font-semibold">
          감사 기록
          <InfoTip label="감사 기록 설명">지금까지 실행한 감사입니다(지워지지 않고 쌓입니다). 누르면 오른쪽에 그 감사 결과를 엽니다.</InfoTip>
          {query.data && <span className="text-[11px] font-normal tabular-nums text-muted-foreground">{data.length}건</span>}
        </h2>
        {query.isPending ? <Skeleton className="h-20 w-full rounded-card" />
          : query.isError ? <ErrorState message="감사 기록을 불러오지 못했습니다." onRetry={() => void query.refetch()} />
          : data.length === 0 ? <p className="py-2 text-sm text-muted-foreground">아직 감사 기록이 없습니다.</p>
          : (
            <ul className="flex flex-col gap-1" aria-label="감사 기록">
              {data.map((a) => (
                <li key={a.id}>
                  <Button variant="ghost" onClick={() => onOpen(a.id)} aria-current={activeId === a.id ? "true" : undefined}
                    className={cn("h-auto w-full flex-col items-start gap-1 whitespace-normal px-3 py-2 text-left font-normal",
                      activeId === a.id && "border bg-muted/60")}>
                    <span className="line-clamp-2 text-sm">{a.preview}</span>
                    <span className="text-[11px] tabular-nums text-muted-foreground">
                      {mmdd(a.created_at)} · 주장 {a.n_claims}{activeId === a.id ? " · 지금 보는 감사" : ""}
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
      </CardContent>
    </Card>
  )
}

function AuditSkeleton({ label }: { label?: string }) {
  return (
    <div className="space-y-3" role="status" aria-busy="true">
      {label && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />{label}</p>}
      {[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 w-full rounded-card" />)}
    </div>
  )
}
