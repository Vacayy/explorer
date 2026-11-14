import { useLayoutEffect, useRef, useState } from "react"
import { useLocation, useSearchParams } from "react-router-dom"
import { GitCommitHorizontal } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import { useDetailBack } from "@/components/shared/DetailNavigation"
import { Markdown } from "@/components/shared/Markdown"
import { cn } from "@/lib/utils"

/**
 * 내러티브 재생성 이력 (D-060). 버전은 supersede되지만 body가 보존됨.
 * - NarrativeTimeline: x축 도트(생성 시점+제목) + 도트 사이 diff. 상세 페이지/인라인 공용.
 * - NarrativeHistory (default): /narrative/history?topic= 상세 페이지 — 도트 클릭 시 본문 열람.
 */

interface NarrativeVersion {
  id: number
  version: number
  title: string | null
  category: string | null
  created_at: string | null
  superseded_at: string | null
}

interface CausalEdge { from: string; to: string }
interface VersionDiff {
  status: string
  added_nodes: string[]
  removed_nodes: string[]
  added_edges: CausalEdge[]
  removed_edges: CausalEdge[]
  summary: string | null
}

interface VersionBodyData {
  status: string
  title: string | null
  narrative: string | null
  created_at: string | null
  version: number | null
}

const fmtDate = (s: string | null) => (s ? s.slice(5, 16).replace("T", " ").replace("-", "/") : "")
/** '2026-08-18 …' → '8/18' */
const shortDay = (s: string | null) => (s ? `${Number(s.slice(5, 7))}/${Number(s.slice(8, 10))}` : "")

/* ---------- 재사용 타임라인 (인라인 + 상세 페이지 공용) ---------- */

/** 처음엔 최근 이만큼만 펼친다 — 앞쪽은 '‹ v1·v2' 칩으로 접는다(§4.33) */
const VISIBLE = 9

export function NarrativeTimeline({ topic, selectedId, onSelectVersion }: {
  topic: string
  selectedId?: number | null
  onSelectVersion: (id: number) => void
}) {
  // undefined = 기본(최신 diff 펼침) · null = 사용자가 접음
  const [expandedDiffId, setExpandedDiffId] = useState<number | null | undefined>(undefined)
  const [showAll, setShowAll] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const { data: versions = [], isLoading, isError } = useQuery(
    apiQuery<NarrativeVersion[]>({
      key: ["spine", "narrative", "versions", topic],
      url: `/api/spine/narrative/versions?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short,
      enabled: !!topic,
    }),
  )
  const asc = [...versions].sort((a, b) => a.version - b.version)
  const hidden = showAll ? [] : asc.slice(0, Math.max(0, asc.length - VISIBLE))
  const shown = asc.slice(hidden.length)
  const latest = asc.at(-1)
  const expanded = expandedDiffId === undefined ? (asc.length > 1 ? latest?.id ?? null : null) : expandedDiffId
  // 처음 열 때 최신 쪽(오른쪽 끝)으로 스크롤 — 버전이 많으면 최신이 화면 밖이었다(§4.33 제안)
  useLayoutEffect(() => {
    const el = scroller.current
    if (el && asc.length) el.scrollLeft = el.scrollWidth
  }, [asc.length])
  if (isLoading) return <Skeleton className="h-40 w-full" />
  if (isError) return <ErrorState message="버전 이력을 불러오지 못했습니다." />
  if (asc.length === 0) return <EmptyState message="저장된 버전이 없습니다." />

  return (
    <Card className="gap-0 py-0" aria-label="버전 타임라인" data-timeline>
      <header className="flex flex-wrap items-baseline gap-x-2 px-4 pt-4">
        <h2 className="text-section font-semibold">버전 {asc.length}개</h2>
        <span className="font-mono text-caption tabular-nums text-muted-foreground">{shortDay(asc[0].created_at)} ~ {shortDay(latest?.created_at ?? null)}</span>
      </header>
      <CardContent className="space-y-3 px-4 py-3">
        <div ref={scroller} className="overflow-x-auto" data-timeline-scroll>
          <div className="flex min-w-max items-start">
            {hidden.length > 0 && (
              <div className="flex h-[7.5rem] items-center pr-2">
                <Button variant="outline" size="xs" onClick={() => setShowAll(true)} aria-label={`앞 버전 ${hidden.length}개 펼치기`}>
                  ‹ {hidden.length <= 3 ? hidden.map((v) => `v${v.version}`).join('·') : `v${hidden[0].version}~v${hidden.at(-1)!.version}`}
                </Button>
              </div>
            )}
            {shown.map((v, i) => (
              <div key={v.id} className="flex items-start">
                {(i > 0 || hidden.length > 0) && (
                  <DiffConnector
                    narrativeId={v.id}
                    active={expanded === v.id}
                    onToggle={() => setExpandedDiffId(expanded === v.id ? null : v.id)}
                  />
                )}
                <DotColumn v={v} selected={selectedId === v.id} onSelect={() => onSelectVersion(v.id)} />
              </div>
            ))}
          </div>
        </div>
        {expanded != null && <DiffDetail narrativeId={expanded} versions={asc} />}
      </CardContent>
    </Card>
  )
}

/* ---------- 상세 페이지 (/narrative/history?topic=&v=) ---------- */

export default function NarrativeHistory() {
  const [sp, setSp] = useSearchParams()
  const location = useLocation()
  const back = useDetailBack(sp.get("topic") ? `/narrative?topic=${encodeURIComponent(sp.get("topic")!)}` : '/narrative', '내러티브로 돌아가기')
  const topic = sp.get("topic") ?? ""
  const vParam = sp.get("v")

  const { data: versions = [] } = useQuery(
    apiQuery<NarrativeVersion[]>({
      key: ["spine", "narrative", "versions", topic],
      url: `/api/spine/narrative/versions?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short,
      enabled: !!topic,
    }),
  )
  const latestId = versions.length ? versions.reduce((a, b) => (a.version >= b.version ? a : b)).id : null
  const picked = Number(vParam) || null
  const activeId = picked ?? latestId

  return <PageContainer gap="sm">
    <Button variant="link" size="sm" className="h-auto self-start px-0 text-caption text-muted-foreground" onClick={back.go}>‹ {back.label}</Button>
    <h1 className="text-page font-semibold">{topic || '내러티브 이력'}</h1>
    {!topic ? <EmptyState message="주제가 지정되지 않았습니다." /> : <>
      <NarrativeTimeline topic={topic} selectedId={activeId} onSelectVersion={id => setSp(prev => {const next=new URLSearchParams(prev);next.set('v',String(id));return next}, {replace:true,state:location.state})} />
      {activeId != null && <VersionBody id={activeId} latest={activeId === latestId} />}
    </>}
  </PageContainer>
}

/* ---------- 도트 (버전) ---------- */

function DotColumn({ v, selected, onSelect }: { v: NarrativeVersion; selected: boolean; onSelect: () => void }) {
  return (
    <div className="flex flex-col items-center w-48 shrink-0">
      <div className={cn("h-12 px-1.5 text-center text-[11px] leading-snug line-clamp-3",
        selected ? "text-foreground font-medium" : "text-muted-foreground")}
        title={v.title ?? undefined}>
        {v.title ?? "(제목 없음)"}
      </div>
      <Button variant="ghost" size="icon" onClick={onSelect} aria-label={`버전 ${v.version} 보기`} aria-pressed={selected}>
        <span aria-hidden="true" className={cn("size-4 rounded-full border-2", selected ? "bg-hypothesis border-hypothesis" : "bg-card border-muted-foreground/50")} />
      </Button>
      <div className={cn("mt-1.5 text-[11px] tabular-nums", selected ? "text-hypothesis font-semibold" : "text-muted-foreground")}>
        v{v.version}
      </div>
      <div className="text-[10px] text-muted-foreground tabular-nums">{fmtDate(v.created_at)}</div>
    </div>
  )
}

/* ---------- 도트 사이 diff 커넥터 ---------- */

function useDiff(narrativeId: number) {
  return useQuery(
    apiQuery<VersionDiff>({
      key: ["spine", "narrative", "diff", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/diff`,
      staleTime: STALE.short,
    }),
  )
}

function DiffConnector({ narrativeId, active, onToggle }: { narrativeId: number; active: boolean; onToggle: () => void }) {
  const { data } = useDiff(narrativeId)
  const added = data?.added_edges.length ?? 0
  const removed = data?.removed_edges.length ?? 0
  const changed = added > 0 || removed > 0

  return (
    <div className="flex flex-col items-center w-24 shrink-0">
      <div className="h-12" />
      {/* 도트(h-4)의 세로 중앙에 선 정렬 */}
      <div className="flex h-4 w-full items-center">
        <div className="h-px flex-1 bg-border" />
      </div>
      <button
        onClick={onToggle}
        disabled={!changed}
        className={cn("mt-1 inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[10px] transition-colors",
          !changed ? "text-muted-foreground/50 cursor-default"
            : active ? "bg-primary/10 text-primary border border-primary/40"
              : "text-primary hover:bg-primary/5 border border-primary/30")}
      >
        <GitCommitHorizontal className="h-3 w-3" />
        {changed ? (
          <span className="tabular-nums">
            {added > 0 && <span>+{added}</span>}
            {added > 0 && removed > 0 && " "}
            {removed > 0 && <span className="text-muted-foreground">−{removed}</span>}
          </span>
        ) : (
          <span>변화 없음</span>
        )}
      </button>
    </div>
  )
}

/* ---------- 펼친 diff 상세 ---------- */

function DiffDetail({ narrativeId, versions }: { narrativeId: number; versions: NarrativeVersion[] }) {
  const { data } = useDiff(narrativeId)
  const cur = versions.find((v) => v.id === narrativeId)
  const prevV = cur ? cur.version - 1 : null
  if (!data || data.status !== "ok") return null
  return (
    <Card className="border-primary/30">
      <CardContent className="py-3 space-y-1.5 text-xs">
        <div className="text-[11px] font-medium text-primary">
          v{prevV} → v{cur?.version} 달라진 것
        </div>
        {data.summary && <p className="text-muted-foreground">{data.summary}</p>}
        {data.added_edges.length > 0 && (
          <div className="text-primary">
            + {data.added_edges.map((e) => `${e.from}→${e.to}`).join(" · ")}
          </div>
        )}
        {data.removed_edges.length > 0 && (
          <div className="text-muted-foreground line-through decoration-muted-foreground/50">
            {data.removed_edges.map((e) => `${e.from}→${e.to}`).join(" · ")}
          </div>
        )}
        {data.added_edges.length === 0 && data.removed_edges.length === 0 && (
          <p className="text-muted-foreground">인과 구조 변화 없음 (본문 표현만 갱신)</p>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 선택 버전 본문 ---------- */

function VersionBody({ id, latest }: { id: number; latest: boolean }) {
  const { data, isLoading } = useQuery(
    apiQuery<VersionBodyData>({
      key: ["spine", "narrative", "version", id],
      url: `/api/spine/narrative/version?id=${id}`,
      staleTime: STALE.medium,
    }),
  )
  if (isLoading) return <Skeleton className="h-48 w-full" />
  if (!data || data.status !== "cached" || !data.narrative) {
    return <EmptyState message="이 버전의 본문을 불러올 수 없습니다." />
  }
  return (
    <article className="space-y-3" data-version-body>
      <p className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
        <Badge variant="secondary" className="font-mono text-[11px]">v{data.version}</Badge>
        <span className="font-mono tabular-nums">{fmtDate(data.created_at)}</span>
        {latest && <span>· 지금 보는 버전(최신)</span>}
      </p>
      <h2 className="text-lg font-semibold leading-snug [overflow-wrap:anywhere]">{data.title}</h2>
      <Markdown className="[overflow-wrap:anywhere]">{data.narrative}</Markdown>
    </article>
  )
}
