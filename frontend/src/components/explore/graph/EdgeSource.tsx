import { ExternalLink, FileText, Loader2 } from "lucide-react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { formatNumber } from "@/utils/format"
import { cn } from "@/lib/utils"

/** 인과 엣지 출처 (D-204) — 모델이 댄 근거 인용을 원문에서 확인한 것만 '출처'로 보인다. */
export type SourceStatus = "document" | "verified" | "unverified" | "scenario" | "legacy_unverified"

interface SourceDoc {
  id: number; source_type: string; channel: string | null; title: string | null; published_at: string | null
  url: string | null; chars: number; excerpt: string; thin: boolean
}
interface EdgeSourceDetail {
  edge_id: number; from: string; to: string; status: SourceStatus; quote: string | null
  epistemic_type: string | null; confidence: number | null; mechanism: string | null
  doc: SourceDoc | null
  evidence: { narrative_id: number; narrative_title: string | null; quote: string | null; doc: SourceDoc | null }[]
  recorded_doc_id: number | null
}

export const SOURCE_LABEL: Record<SourceStatus, string> = {
  document: "출처 문서", verified: "근거 인용 확인", unverified: "출처 미확인",
  scenario: "가정 시나리오", legacy_unverified: "출처 미확인(이전 방식)",
}
const SOURCE_NOTE: Record<SourceStatus, string> = {
  document: "이 문서 하나를 읽고 추출한 인과입니다.",
  verified: "내러티브 생성 때 모델이 댄 인용을 원문에서 글자 그대로 찾았습니다.",
  unverified: "모델이 근거 문서를 대지 않았거나 인용이 원문에 없었습니다. 추론으로 만든 고리일 수 있습니다.",
  scenario: "가정한 사건에서 출발한 시나리오 체인입니다. 문서 출처가 없습니다.",
  legacy_unverified: "출처 검증 도입(D-204) 전에 내러티브가 만든 엣지입니다. 당시 입력 묶음의 마지막 문서가 기록됐을 뿐이라 출처로 볼 수 없습니다.",
}
const KIND: Record<string, string> = { telegram: "텔레그램", blog: "블로그", youtube: "유튜브", transcript: "컨콜", scrap: "스크랩", note: "노트" }

export const isSourced = (status?: string | null) => status === "document" || status === "verified"

function DocCard({ doc, quote }: { doc: SourceDoc; quote?: string | null }) {
  return (
    <div className="space-y-1.5 rounded-lg border p-2.5">
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <Badge variant="secondary" className="text-[10px] font-normal">{KIND[doc.source_type] ?? doc.source_type}</Badge>
        {doc.channel && <span className="font-medium text-foreground">{doc.channel}</span>}
        {doc.published_at && <span>{doc.published_at.slice(0, 10)}</span>}
        <span>· 본문 {formatNumber(doc.chars)}자</span>
      </div>
      <p className="text-sm font-medium leading-snug">{doc.title || "(제목 없음)"}</p>
      {quote && <blockquote className="border-l-2 border-primary/50 pl-2 text-xs leading-snug">“{quote}”</blockquote>}
      {doc.thin && <p className="text-[11px] text-hypothesis">한두 줄짜리 전언입니다. 수치·데이터의 원출처가 본문에 없을 수 있습니다.</p>}
      <div className="flex flex-wrap gap-1">
        <Button asChild variant="ghost" size="sm" className="h-7 px-2 text-xs"><Link to={`/doc/${doc.id}`}><FileText className="size-3.5" />문서 보기</Link></Button>
        {doc.url && <Button asChild variant="ghost" size="sm" className="h-7 px-2 text-xs"><a href={doc.url} target="_blank" rel="noreferrer"><ExternalLink className="size-3.5" />원문</a></Button>}
      </div>
    </div>
  )
}

function Detail({ edgeId }: { edgeId: number }) {
  const q = useQuery({
    queryKey: ["spine", "causal", "edge-source", edgeId],
    queryFn: async () => (await api.get<EdgeSourceDetail>(`/api/spine/causal/edge/${edgeId}/source`)).data,
    staleTime: 5 * 60_000,
  })
  if (q.isPending) return <div role="status" className="flex items-center gap-2 p-1 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />출처를 불러오는 중</div>
  if (q.isError || !q.data) return <div className="space-y-2 p-1 text-xs"><p>출처를 불러오지 못했습니다.</p><Button size="sm" variant="outline" onClick={() => q.refetch()}>다시 시도</Button></div>
  const d = q.data
  const others = d.evidence.filter(ev => ev.doc && ev.doc.id !== d.doc?.id)
  return (
    <div className="space-y-2.5">
      <div className="space-y-1">
        <p className="text-xs font-medium">{d.from} → {d.to}</p>
        <p className="text-[11px] text-muted-foreground">{SOURCE_NOTE[d.status]}</p>
        {d.epistemic_type === "hypothesis" && <p className="text-[11px] text-muted-foreground">가설 · 확신 {d.confidence != null ? d.confidence.toFixed(2) : "-"}</p>}
      </div>
      {d.doc && <DocCard doc={d.doc} quote={d.quote} />}
      {others.length > 0 && <div className="space-y-1.5">
        <p className="text-[11px] font-medium text-muted-foreground">다른 내러티브에서 확인된 근거 {formatNumber(others.length)}건</p>
        {others.slice(0, 3).map(ev => ev.doc && <DocCard key={`${ev.narrative_id}-${ev.doc.id}`} doc={ev.doc} quote={ev.quote} />)}
      </div>}
      {!d.doc && others.length === 0 && d.status !== "scenario" && <p className="text-[11px] text-muted-foreground">확인된 출처 문서가 없습니다. 이 인과를 근거로 판단하지 마세요.</p>}
    </div>
  )
}

/** 엣지 행 안의 출처 배지. 누르면 출처 상세(문서·인용·채널·게시일)를 연다. id가 없는 엣지는 배지만. */
export function EdgeSourceBadge({ edgeId, status }: { edgeId?: number; status?: SourceStatus | null }) {
  if (!status) return null
  const sourced = isSourced(status)
  const badge = <Badge variant="outline" className={cn("text-[9px] font-normal", sourced ? "border-primary/40 text-primary" : "border-hypothesis/40 text-hypothesis")}>{SOURCE_LABEL[status]}</Badge>
  if (!edgeId) return badge
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" aria-label={`출처 보기 · ${SOURCE_LABEL[status]}`} onClick={e => e.stopPropagation()}>{badge}</button>
      </PopoverTrigger>
      <PopoverContent className="w-80 max-w-[calc(100vw-2rem)]" align="start" onClick={e => e.stopPropagation()}><Detail edgeId={edgeId} /></PopoverContent>
    </Popover>
  )
}

/** 노드 패널 머리 — 이 노드에 붙은 인과 중 출처가 확인된 것과 아닌 것. */
export function NodeSourceSummary({ statuses }: { statuses: (SourceStatus | null | undefined)[] }) {
  if (!statuses.length) return null
  const sourced = statuses.filter(isSourced).length
  const rest = statuses.length - sourced
  return (
    <p className={cn("rounded-md px-2 py-1.5 text-[11px]", sourced === 0 ? "bg-hypothesis/10 text-hypothesis" : "bg-muted text-muted-foreground")}>
      연결된 인과 {formatNumber(statuses.length)}개 중 출처 확인 {formatNumber(sourced)}개 · 미확인 {formatNumber(rest)}개.
      {sourced === 0 && " 이 노드는 확인된 문서 근거 없이 만들어졌습니다."} 각 인과의 배지를 누르면 출처를 볼 수 있습니다.
    </p>
  )
}
