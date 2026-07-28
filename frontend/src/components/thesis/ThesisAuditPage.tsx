import { useState } from "react"
import { Gauge, History, Sparkles, TrendingUp } from "lucide-react"
import { PageContainer } from "@/components/shared/PageContainer"
import { OutlookSubNav } from "@/components/explore/OutlookSubNav"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { useRunThesisAudit, useThesisAudits, useThesisAudit } from "@/hooks/useThesisAudit"
import type { ThesisAudit, ThesisClaim, ThesisEdge, ThesisVerdict } from "@/types"

/**
 * /thesis — 논지 감사 (thesis audit, docs/specs/thesis-audit.md). 전망(미래·확률) 서브탭.
 * 내 thesis를 축적된 인과그래프에 **대질**(read-only 감사, 등재 아님) — 일치/충돌/반박/신규 델타.
 * moat는 추론이 아니라 정박: 모든 판정이 코퍼스 근거(엣지·독립 소스·시점)를 가리킨다.
 */
export default function ThesisAuditPage() {
  const [text, setText] = useState("")
  const [viewId, setViewId] = useState<number | null>(null)
  const run = useRunThesisAudit()
  const loaded = useThesisAudit(viewId)

  const audit: ThesisAudit | undefined = viewId != null ? loaded.data : run.data

  function submit() {
    setViewId(null)
    run.mutate(text.trim())
  }

  return (
    <PageContainer gap="sm">
      <OutlookSubNav />

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Gauge className="h-4 w-4 text-muted-foreground" /> 논지 감사
            <span className="text-[11px] font-normal text-muted-foreground">
              내 thesis를 인과그래프에 대질 — read-only(등재 아님)
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Textarea rows={6} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="투자 논지를 붙여넣으세요. 여러 주장으로 나눠 각각을 그래프의 인과 엣지·독립 소스·시간 급증에 대질합니다." />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={submit} disabled={run.isPending || text.trim().length < 10}>
              {run.isPending ? "감사 중… (분해→정박→판정, ~수 분)" : "감사 실행"}
            </Button>
            {run.isError && <span className="text-xs text-[var(--color-chart-negative)]">실패 — 다시 시도</span>}
          </div>
        </CardContent>
      </Card>

      {run.isPending && <AuditSkeleton />}
      {viewId != null && loaded.isLoading && <AuditSkeleton />}
      {viewId != null && loaded.isError && <ErrorState onRetry={() => loaded.refetch()} />}

      {audit && <AuditResult audit={audit} />}

      <HistoryList onOpen={setViewId} activeId={viewId} />
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

function AuditResult({ audit }: { audit: ThesisAudit }) {
  const counts = audit.claims.reduce<Record<string, number>>((a, c) => {
    a[c.verdict] = (a[c.verdict] ?? 0) + 1; return a
  }, {})
  return (
    <div className="space-y-3">
      {/* 요약 — 델타 분포 */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted-foreground">주장 {audit.n_claims} —</span>
        {(["aligned", "contested", "challenged", "novel"] as ThesisVerdict[]).filter((v) => counts[v]).map((v) => (
          <span key={v} className="inline-flex items-center gap-1" style={{ color: VERDICT[v].color }}>
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: VERDICT[v].color }} />
            {VERDICT[v].label} {counts[v]}
          </span>
        ))}
      </div>
      {audit.claims.map((c, i) => <ClaimCard key={i} claim={c} />)}
    </div>
  )
}

function ClaimCard({ claim }: { claim: ThesisClaim }) {
  const v = VERDICT[claim.verdict]
  const rel = claim.edges.filter((e) => e.stance !== "context").slice(0, 4)
  const ctx = claim.edges.filter((e) => e.stance === "context").slice(0, 2)
  return (
    <Card>
      <CardContent className="py-3 space-y-2">
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
        </div>

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
      </CardContent>
    </Card>
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

function HistoryList({ onOpen, activeId }: { onOpen: (id: number) => void; activeId: number | null }) {
  const { data = [], isLoading } = useThesisAudits()
  if (isLoading) return <Skeleton className="h-20 w-full rounded-xl" />
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <History className="h-4 w-4 text-muted-foreground" /> 감사 히스토리
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <EmptyState message="아직 감사 기록이 없습니다 — 위에 논지를 붙여넣고 실행하세요." />
        ) : (
          <ul className="divide-y">
            {data.map((a) => (
              <li key={a.id}>
                <button onClick={() => onOpen(a.id)}
                  className={`w-full text-left flex items-center gap-2 py-1.5 hover:bg-muted/50 rounded px-1 ${activeId === a.id ? "bg-muted/60" : ""}`}>
                  <span className="text-sm truncate min-w-0 flex-1">{a.preview}</span>
                  <span className="text-[10px] text-muted-foreground shrink-0">주장 {a.n_claims}</span>
                  <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">{a.created_at.slice(0, 10)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function AuditSkeleton() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 w-full rounded-xl" />)}
    </div>
  )
}
