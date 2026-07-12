import { useState } from "react"
import { Link } from "react-router-dom"
import { BookOpenCheck, ChevronDown, Loader2, Swords } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { cn } from "@/lib/utils"

/**
 * /knowledge — 지식 익스플로러 (탐색의 발견 표면, K1/K2).
 * 시스템이 반복·독립 관측으로 승격한 지식을 activation 순으로 펼친다.
 * 각 지식은 근거 사슬(어떤 문서가 지지/반박했나)로 depth — 스캔 표면 원칙.
 * contested(충돌 중)는 강조 — 판단은 사람이.
 */

interface KnowledgeEntity {
  name: string
  type: string
  aliases: string | null
}

interface KnowledgeItem {
  id: number
  statement: string
  epistemic_status: string
  pace_layer: string
  support: number
  refute: number
  independent: number
  activation: number | null
  entities: KnowledgeEntity[]
  created_at: string
  contested_at: string | null
}

interface EvidenceDoc {
  doc_id: number | null
  title: string | null
  source_type: string | null
  stance: string
  independent: boolean
  observed_at: string
}

const LAYER_LABEL: Record<string, string> = {
  event: "사건", flow: "흐름", cycle: "사이클", structure: "구조", regime: "체제",
}
const EPISTEMIC_LABEL: Record<string, string> = {
  observed: "관측됨", corroborated: "교차확인", contested: "충돌 중",
  hypothesis: "가설", superseded: "대체됨",
}

export default function KnowledgePage() {
  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<KnowledgeItem[]>({
      key: ["spine", "knowledge", "items"],
      url: "/api/spine/knowledge/items",
      staleTime: STALE.short,
    }),
  )

  if (isLoading) return <KnowledgeSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <BookOpenCheck className="h-5 w-5 text-muted-foreground" /> 지식
        </h2>
        <span className="text-xs text-muted-foreground">
          반복·독립 관측으로 승격된 시스템의 전제 {data.length}건 — 활성도 순
        </span>
      </div>

      {data.length === 0 ? (
        <EmptyState message="아직 승격된 지식이 없습니다. 주간 승격 배치가 후보를 만들면 홈 승인 카드에서 심사할 수 있습니다." />
      ) : (
        <div className="space-y-2">
          {data.map((k) => <KnowledgeCard key={k.id} item={k} />)}
        </div>
      )}
    </PageContainer>
  )
}

function KnowledgeCard({ item: k }: { item: KnowledgeItem }) {
  const [open, setOpen] = useState(false)
  const contested = k.epistemic_status === "contested"

  return (
    <Card className={cn(contested && "border-destructive/40 border-l-2 border-l-destructive")}>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge variant="secondary" className="text-[10px]">{LAYER_LABEL[k.pace_layer] ?? k.pace_layer}층</Badge>
          <Badge
            variant="outline"
            className={cn("text-[10px]",
              contested ? "text-destructive border-destructive/50"
                : k.epistemic_status === "corroborated" ? "text-primary border-primary/40"
                : "text-muted-foreground")}
          >
            {contested && <Swords className="h-2.5 w-2.5 mr-0.5" />}
            {EPISTEMIC_LABEL[k.epistemic_status] ?? k.epistemic_status}
          </Badge>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            독립 관측 {k.independent} · 지지 {k.support}
            {k.refute > 0 && <span className="text-destructive"> · 반박 {k.refute}</span>}
          </span>
          <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">
            {k.created_at.slice(0, 10)} 승격
          </span>
        </div>

        <p className="text-sm leading-snug">{k.statement}</p>

        {k.entities.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {k.entities.map((e) => (
              <Link
                key={`${e.type}-${e.name}`}
                to={e.type === "company" && e.aliases ? `/analyze/${e.aliases}/summary`
                  : e.type === "person" ? `/person?name=${encodeURIComponent(e.name)}`
                  : `/feed?${e.type === "industry" || e.type === "sector" ? "industry" : "topic"}=${encodeURIComponent(e.name)}`}
              >
                <Badge variant="outline" className="text-[10px] font-normal hover:border-primary hover:text-primary">
                  {e.name}
                </Badge>
              </Link>
            ))}
          </div>
        )}

        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="group/ev flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/ev:rotate-180" />
            근거 사슬 {k.support + k.refute}건
          </CollapsibleTrigger>
          <CollapsibleContent>
            {open && <EvidenceList knowledgeId={k.id} />}
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

function EvidenceList({ knowledgeId }: { knowledgeId: number }) {
  const { data, isLoading } = useQuery(
    apiQuery<EvidenceDoc[]>({
      key: ["spine", "knowledge", knowledgeId, "evidence"],
      url: `/api/spine/knowledge/items/${knowledgeId}/evidence`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
        <Loader2 className="h-3 w-3 animate-spin" /> 근거 불러오는 중…
      </div>
    )
  }
  return (
    <ul className="mt-1.5 divide-y rounded-md border px-3">
      {(data ?? []).map((ev, i) => (
        <li key={i} className="flex items-center gap-2 py-1.5">
          <Badge
            variant={ev.stance === "refute" ? "destructive" : "secondary"}
            className="text-[9px] shrink-0"
          >
            {ev.stance === "refute" ? "반박" : ev.stance === "attention" ? "주목" : "지지"}
          </Badge>
          {!ev.independent && (
            <Badge variant="outline" className="text-[9px] shrink-0 text-muted-foreground">릴레이</Badge>
          )}
          {ev.source_type && <SourceBadge sourceType={ev.source_type} />}
          {ev.doc_id ? (
            <Link to={`/doc/${ev.doc_id}`} className="text-xs truncate hover:underline">
              {ev.title || `문서 #${ev.doc_id}`}
            </Link>
          ) : (
            <span className="text-xs text-muted-foreground">(사용자 행위)</span>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground tabular-nums">
            {ev.observed_at.slice(0, 10)}
          </span>
        </li>
      ))}
    </ul>
  )
}

function KnowledgeSkeleton() {
  return (
    <PageContainer gap="sm">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-32 w-full rounded-xl" />
      <Skeleton className="h-32 w-full rounded-xl" />
      <Skeleton className="h-32 w-full rounded-xl" />
    </PageContainer>
  )
}
