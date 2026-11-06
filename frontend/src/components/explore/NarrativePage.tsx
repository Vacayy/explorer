import { useEffect, useState, type ReactNode } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { Anchor, MessageCircle, ArrowRight, HelpCircle, Loader2, RefreshCw, Route, Sparkles, Workflow } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { DetailSection } from "@/components/shared/DetailLayout"
import { DetailLink as Link, useDetailBack, useDetailOrigin, rememberDetailOrigin } from "@/components/shared/DetailNavigation"
import { askQuestion } from "@/api/spine"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { Markdown } from "@/components/shared/Markdown"
import { PageContainer } from "@/components/shared/PageContainer"
import SaveButton from "@/components/shared/SaveButton"
import { NarrativeList } from "@/components/explore/NarrativeList"
import { BigPictureCard, PremisesCard } from "@/components/world/BigPictureCard"
import { NarrativeCheckpoint } from "@/components/world/NarrativeCheckpoint"
import { MarketTodayTimeline } from "@/components/world/MarketTodayTimeline"
import { NarrativeCandidatesCard } from "@/components/world/NarrativeCandidatesCard"
import { BeneficiaryList, ScenarioBeneficiaries, type ScenarioBeneficiary } from "@/components/explore/graph/CausalDetail"
import { ChevronDown, FileText } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { useNarrativeIndex } from "@/hooks/useWorld"
import { splitSummary } from "@/lib/bigPicture"
import { formatPp, formatRatio } from "@/utils/format"
import { cn } from "@/lib/utils"
import { EdgeSourceBadge, type SourceStatus } from "@/components/explore/graph/EdgeSource"

/**
 * /narrative?topic= — 주제 내러티브 (theme_surge 고도화, D-023 인과 그래프 위 서브그래프).
 * 질문형 제목 + 서사(md) + 인과 체인 구조 뷰(그래프에서 조회) + category/version.
 * 도시에 2단 패턴: GET 캐시 → stale이면 compute 자동 발화.
 */
interface Narrative {
  status: string
  title: string | null
  narrative: string | null
  created_at: string | null
  stale: boolean
  category: string | null
  version: number | null
  narrative_id: number | null
}

const LENS_LABEL: Record<string, string> = {
  macro: "매크로", geopolitics: "지정학", industry: "산업", flow: "수급", tech: "기술", policy: "정책",
}

export default function NarrativePage() {
  const [sp, setSp] = useSearchParams()
  const location = useLocation()
  const origin = useDetailOrigin()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const topic = sp.get("topic") ?? ""
  const tab = ['current','evidence','history','explore'].includes(sp.get('detail_tab') || '') ? sp.get('detail_tab')! : 'current'
  const discussion = useMutation({ mutationFn: (question: string) => askQuestion({ question }),
    onSuccess: result => { if (result.conversation_id) navigate(`/chat?id=${result.conversation_id}`) } })


  const cached = useQuery(
    apiQuery<Narrative>({
      key: ["spine", "narrative", topic],
      url: `/api/spine/narrative?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short, enabled: !!topic,
    }),
  )
  // 자동 재생성은 **7일에 1회**로 제한 (D-122 — 기존 24h). stale(새 문서 있음)이라도 최근 갱신이
  // 7일 내면 자동 발화 금지. 진입만으로 opus가 도는 경로가 토큰 소모의 큰 축이었고, 지금은
  // 새로고침 버튼이 있어 사람이 원할 때 즉시 돌릴 수 있다.
  // 재료가 없으면 백엔드가 doc_ids_hash로 no-op(status=cached).
  const [refreshNonce, setRefreshNonce] = useState(0)
  const AUTO_REGEN_HOURS = 24 * 7
  const createdAt = cached.data?.created_at
  const ageHours = createdAt
    ? (Date.now() - new Date(createdAt.replace(" ", "T") + "Z").getTime()) / 3.6e6
    : Infinity
  const autoStale = !!cached.data?.stale && ageHours >= AUTO_REGEN_HOURS
  const fresh = useQuery(
    apiComputeQuery<Narrative>({
      key: ["spine", "narrative", topic, "compute", refreshNonce],
      url: `/api/spine/narrative/compute?topic=${encodeURIComponent(topic)}`,
      enabled: !!topic && (autoStale || refreshNonce > 0),
    }),
  )
  // 생성 완료 시 캐시·버전 목록 무효화. 수동 새로고침이면 결과(갱신됨 vs 재료 없음)를 토스트로 알림.
  useEffect(() => {
    if (!fresh.data || fresh.isFetching) return
    if (fresh.data.status === "fresh") {
      qc.invalidateQueries({ queryKey: ["spine", "narrative", topic] })
      qc.invalidateQueries({ queryKey: ["spine", "narrative", "versions", topic] })
      if (refreshNonce > 0) toast.success("내러티브를 새로 갱신했습니다")
    } else if (refreshNonce > 0 && fresh.data.status === "cached") {
      toast("새로 반영할 재료가 없어 갱신하지 않았습니다")
    }
  }, [fresh.data, fresh.isFetching, refreshNonce, topic, qc])
  const n = fresh.data ?? cached.data
  const index = useNarrativeIndex()

  // topic 없이 진입 = Thesis › 지금 랜딩
  if (!topic) return <NarrativeLanding />
  const generating = fresh.isFetching
  const version = n?.version
  const narrativeId = n?.narrative_id
  const meta = index.get(topic)
  const { summary, body } = splitSummary(n?.narrative ?? '')
  // 근거·추가 탐구 펼침 = URL ?detail_tab=evidence|explore (옛 탭 주소 그대로). 'history'는 오른쪽 버전 이력이 늘 보인다
  const openPart = (part: 'evidence' | 'explore') => (o: boolean) => setSp(prev => { const next = new URLSearchParams(prev); if (o) next.set('detail_tab', part); else next.delete('detail_tab'); return next }, { replace: true, state: location.state, preventScrollReset: true })
  return <PageContainer gap="sm">
    <BackLink fallback="/narrative" label="지금 · 서사 목록" />
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]" data-narrative-detail>
      <article className="min-w-0 space-y-4">
        <header className="space-y-2">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">
            <Badge variant="secondary" className="text-[11px]">{topic}</Badge>
            <Badge variant="outline" className="border-hypothesis/40 text-[10px] font-normal text-hypothesis">AI 생성</Badge>
            {version != null && <span className="font-mono tabular-nums">v{version}</span>}
            {n?.created_at && <time dateTime={n.created_at} className="font-mono tabular-nums">{n.created_at.slice(0, 16).replace('T', ' ')}</time>}
            {meta?.share_pct != null && <span>비중 {formatRatio(meta.share_pct)}{meta.share_delta_pp ? ` (${formatPp(meta.share_delta_pp, 1)})` : ''}</span>}
            {meta?.is_surging && <span className="text-up-ink">급등</span>}
            {(n?.category || '').split(',').filter(Boolean).map(l => <span key={l}>{LENS_LABEL[l] || l}</span>)}
          </p>
          {cached.isLoading ? <Skeleton className="h-9 w-3/4" /> : <h1 className="text-page font-semibold leading-snug [overflow-wrap:anywhere]">{n?.title || topic}</h1>}
          <div className="flex flex-wrap items-center gap-2">
            {narrativeId != null && <SaveButton kind="narrative" refId={String(narrativeId)} url={`/narrative/history?topic=${encodeURIComponent(topic)}&v=${narrativeId}`} title={topic} subtitle={version ? `v${version}` : '내러티브'} showLabel />}
            <Button variant="ghost" size="sm" disabled={!n?.narrative || discussion.isPending} onClick={() => discussion.mutate(`아래 저장된 AI 내러티브의 핵심 주장과 근거, 반론을 검토해줘. 원문 사실과 AI 해석을 구분해줘.\n\n주제: ${topic}\n버전: ${version ?? '미상'} (ID ${narrativeId ?? '미상'})\n생성: ${n?.created_at ?? '미상'}\n\n${n?.narrative || ''}`)}><MessageCircle aria-hidden="true" />{discussion.isPending ? '대화 준비 중' : '이 내러티브로 대화'}</Button>
            <Button variant="outline" size="sm" disabled={generating} onClick={() => setRefreshNonce(k => k + 1)}><RefreshCw aria-hidden="true" className={generating ? 'animate-spin' : ''} />갱신</Button>
          </div>
        </header>
        {cached.isError && <ErrorState message="저장된 내러티브를 불러오지 못했습니다." onRetry={() => void cached.refetch()} />}
        {fresh.isError && <p role="alert" className="text-sm text-destructive">갱신에 실패했습니다. 저장된 내용은 계속 읽을 수 있습니다.</p>}
        {discussion.isError && <p role="alert" className="text-sm text-destructive">대화를 시작하지 못했습니다. 다시 시도해 주세요.</p>}
        {generating && <p role="status" className="text-caption text-muted-foreground">새 자료로 내러티브를 갱신하고 있습니다.</p>}
        {cached.isLoading ? <Skeleton className="h-64 w-full" />
          : n?.narrative ? <>
            {summary.length > 0 && <section className="bg-muted/60 px-4 py-3" aria-label="3줄 요약" data-summary-box>
              <h2 className="text-caption font-semibold">3줄 요약</h2>
              <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-relaxed">{summary.map((t, i) => <li key={i}>{t}</li>)}</ol>
            </section>}
            <Markdown className="[overflow-wrap:anywhere] [&_pre]:overflow-x-auto">{body}</Markdown>
          </>
          : !cached.isError && <EmptyState message="저장된 내러티브가 없습니다. 갱신 버튼으로 생성을 요청할 수 있습니다." />}
        <NarrativeCheckpoint topic={topic} />
        <Fold title="근거" open={tab === 'evidence'} onOpenChange={openPart('evidence')}>
          {narrativeId ? <><Grounding narrativeId={narrativeId} /><CausalChain narrativeId={narrativeId} /><ChainPaths narrativeId={narrativeId} /></> : <EmptyState message="연결된 근거가 없습니다." />}
        </Fold>
        <Fold title="추가 탐구" open={tab === 'explore'} onOpenChange={openPart('explore')}>
          <DetailSection title="인과 흐름 (메르 모드)"><MerNarrativeCard topic={topic} /></DetailSection>
          <DetailSection title="파급 시나리오"><ScenarioSection topic={topic} /></DetailSection>
          <DetailSection title="언급 상위 종목"><BeneficiaryList sector={topic} /></DetailSection>
        </Fold>
      </article>
      <aside className="min-w-0 space-y-5" aria-label="상세 맥락">
        {narrativeId != null && <MarketTodayTimeline narrativeId={narrativeId} />}
        {narrativeId != null && <VersionChange narrativeId={narrativeId} />}
        {narrativeId != null && <AsideCausal narrativeId={narrativeId} />}
        <AsideVersions topic={topic} currentId={narrativeId ?? null} origin={origin} />
        {narrativeId != null && <RelatedNarratives narrativeId={narrativeId} />}
        <div>
          <DetailSection title="관련 질문">{narrativeId ? <NarrativeQuestions narrativeId={narrativeId} /> : <EmptyState message="연결된 버전이 없습니다." />}</DetailSection>
          <DetailSection title="관련 리포트"><ReportLinkCard topic={topic} /></DetailSection>
        </div>
      </aside>
    </div>
  </PageContainer>
}

/** '‹ 돌아갈 곳' 한 줄 — 들어온 화면을 기억하면 그리로(DetailNavigation) */
function BackLink({ fallback, label }: { fallback: string; label: string }) {
  const back = useDetailBack(fallback, label)
  return <Button variant="link" size="sm" className="h-auto self-start px-0 text-caption text-muted-foreground" onClick={back.go}>‹ {back.label.replace(/로 돌아가기$/, '')}</Button>
}

/** 본문 아래 접힘 칸 — 근거·추가 탐구(옛 탭). 닫혀 있으면 내용(조회)을 그리지 않는다 */
function Fold({ title, open, onOpenChange, children }: { title: string; open: boolean; onOpenChange: (o: boolean) => void; children: ReactNode }) {
  return <Collapsible open={open} onOpenChange={onOpenChange} className="border-t pt-2">
    <CollapsibleTrigger asChild><Button variant="ghost" className="group h-auto w-full justify-between px-0 text-left font-semibold">{title}<ChevronDown aria-hidden="true" className="transition-transform group-data-[state=open]:rotate-180" /></Button></CollapsibleTrigger>
    <CollapsibleContent className="space-y-4 pt-3">{children}</CollapsibleContent>
  </Collapsible>
}

interface VersionDiffData {
  status: string; added_nodes: string[]; removed_nodes: string[]
  added_edges: { from: string; to: string }[]; removed_edges: { from: string; to: string }[]; summary: string | null
}

/** 이번 버전에서 바뀐 것 — 저장된 드리프트 요약 + 추가·삭제 노드(결정적 diff, summarize=false라 새로 만들지 않는다) */
function VersionChange({ narrativeId }: { narrativeId: number }) {
  const { data } = useQuery(apiQuery<VersionDiffData>({
    key: ["spine", "narrative", "diff", narrativeId, "stored"], url: `/api/spine/narrative/${narrativeId}/diff`, params: { summarize: false }, staleTime: STALE.short,
  }))
  if (!data || data.status !== 'ok') return null
  const nodes = [...data.added_nodes.map(x => ['+', x]), ...data.removed_nodes.map(x => ['−', x])]
  if (!data.summary && nodes.length === 0) return null
  return <section className="space-y-2" data-version-change>
    <h2 className="border-b pb-1 text-sm font-semibold">이번 버전에서 바뀐 것</h2>
    {data.summary && <p className="text-sm leading-relaxed text-muted-foreground">{data.summary}</p>}
    {nodes.length > 0 && <div className="flex flex-wrap gap-1">{nodes.slice(0, 12).map(([k, x]) => <span key={k + x} className={cn('px-1.5 py-0.5 text-[11px]', k === '+' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground')}>{k} {x}</span>)}</div>}
  </section>
}

/** 인과 고리 — 이 버전의 엣지(원인 → 결과 · 신뢰 · 메커니즘), 6개까지. 전체는 아래 '근거' */
function AsideCausal({ narrativeId }: { narrativeId: number }) {
  const { data } = useQuery(apiQuery<CausalGraph>({ key: ["spine", "narrative", "causal", narrativeId], url: `/api/spine/narrative/${narrativeId}/causal`, staleTime: STALE.short }))
  const edges = data?.edges ?? []
  if (edges.length === 0) return null
  return <section className="space-y-1" data-aside-causal>
    <h2 className="border-b pb-1 text-sm font-semibold">인과 고리</h2>
    <ul className="divide-y">{edges.slice(0, 6).map((e, i) => <li key={i} className="space-y-0.5 py-2">
      <p className="text-sm font-medium">{e.from} → {e.to}{e.confidence != null && <span className="ml-1 font-mono text-[11px] font-normal text-muted-foreground">신뢰 {e.confidence.toFixed(2)}</span>}</p>
      {e.mechanism && <p className="line-clamp-3 text-xs text-muted-foreground">{e.mechanism}</p>}
    </li>)}</ul>
  </section>
}

/** 버전 이력 — 최신 6개(제목·날짜), 누르면 그 버전을 이력 화면에서 */
function AsideVersions({ topic, currentId, origin }: { topic: string; currentId: number | null; origin: ReturnType<typeof useDetailOrigin> }) {
  const navigate = useNavigate()
  const { data = [] } = useQuery(apiQuery<{ id: number; version: number; title: string | null; created_at: string | null }[]>({
    key: ["spine", "narrative", "versions", topic], url: `/api/spine/narrative/versions?topic=${encodeURIComponent(topic)}`, staleTime: STALE.short, enabled: !!topic,
  }))
  if (data.length === 0) return null
  const go = (id: number) => { rememberDetailOrigin(origin); navigate(`/narrative/history?topic=${encodeURIComponent(topic)}&v=${id}`, { state: { detailOrigin: origin } }) }
  return <section className="space-y-1" data-aside-versions>
    <h2 className="flex items-baseline border-b pb-1 text-sm font-semibold">버전 이력<Button variant="link" size="sm" className="ml-auto h-auto px-0 text-caption font-normal text-muted-foreground" onClick={() => go(currentId ?? data[0].id)}>전체 {data.length}개 ›</Button></h2>
    <ul className="divide-y">{data.slice(0, 6).map(v => <li key={v.id}>
      <button type="button" onClick={() => go(v.id)} className="grid w-full grid-cols-[2.5rem_1fr] gap-x-2 py-2 text-left hover:bg-muted/40">
        <span className="font-mono text-xs text-muted-foreground">v{v.version}</span>
        <span className="min-w-0"><span className={cn('line-clamp-2 text-sm', v.id === currentId && 'font-semibold')}>{v.title ?? '(제목 없음)'}</span>
          <span className="font-mono text-[11px] text-muted-foreground">{(v.created_at ?? '').slice(0, 10)}</span></span>
      </button>
    </li>)}</ul>
  </section>
}

/* ---------- 이 서사의 핵심질문 (D-067 2d 미러링) — 질문 트래커와 내러티브 연결 ---------- */

const QV: Record<string, { label: string; cls: string }> = {
  leaning_yes: { label: "긍정", cls: "text-primary border-primary/40" },
  leaning_no: { label: "부정", cls: "text-destructive border-destructive/50" },
  mixed: { label: "혼조", cls: "text-hypothesis border-hypothesis/40" },
  unknown: { label: "미판정", cls: "text-muted-foreground border-border" },
}

function NarrativeQuestions({ narrativeId }: { narrativeId: number }) {
  const { data = [] } = useQuery(
    apiQuery<{ id: number; text: string; status: string; lead_verdict: string | null; confirm_verdict: string | null }[]>({
      key: ["spine", "questions", "narrative", narrativeId],
      url: `/api/spine/questions?narrative_id=${narrativeId}`, staleTime: STALE.short,
    }),
  )
  if (data.length === 0) return null
  return (
    <Card><CardContent className="py-3 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <HelpCircle className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium">이 서사가 던지는 핵심질문</span>
        <span className="text-[11px] text-muted-foreground">분할정복으로 추적 · 질문을 누르면 상세</span>
      </div>
      {data.map((q) => (
        <Link key={q.id} to={`/question/${q.id}`}
          className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 hover:border-primary">
          <span className="text-[13px] flex-1">{q.text}</span>
          {q.status === "proposed" ? (
            <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40 shrink-0">제안됨</Badge>
          ) : (
            <span className="flex shrink-0 gap-1">
              <Badge variant="outline" className={cn("text-[10px]", QV[q.confirm_verdict ?? "unknown"].cls)}>
                확정 {QV[q.confirm_verdict ?? "unknown"].label}
              </Badge>
              <Badge variant="outline" className={cn("text-[10px]", QV[q.lead_verdict ?? "unknown"].cls)}>
                선행 {QV[q.lead_verdict ?? "unknown"].label}
              </Badge>
            </span>
          )}
        </Link>
      ))}
    </CardContent></Card>
  )
}

/* ---------- 랜딩 (Thesis › 지금 — topic 없이 진입) ---------- */

/** Thesis › 지금 (ia-redesign §4.25) — 이번 주 큰 그림 → 전제 칸 | 내러티브 후보(§9.3) → 서사 목록(이번 주 바뀐 것 필터·고리 펼침). 전부 저장분 조회 */
function NarrativeLanding() {
  const count = useNarrativeIndex().size
  return (
    <PageContainer gap="sm">
      <h1 className="text-page font-semibold">지금</h1>
      <BigPictureCard />
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <PremisesCard />
        <NarrativeCandidatesCard />
      </div>
      <Card className="gap-0 py-0" aria-label="서사 목록">
        <header className="flex items-baseline gap-2 border-b px-4 py-3">
          <h2 className="text-section font-semibold">서사 목록</h2>
          {count > 0 && <span className="font-mono text-caption tabular-nums text-muted-foreground">{count}편</span>}
        </header>
        <div className="p-4"><NarrativeList empty="state" controls fold={10} /></div>
      </Card>
    </PageContainer>
  )
}

/* ---------- 파급 시나리오 (scenario 엔진 연결 — '왜·그래서 무엇', 온디맨드 opus) ---------- */

interface ScenarioResult {
  status: string
  answer: string | null
  beneficiaries: ScenarioBeneficiary[]
  citations: { n: number; doc_id: number; title: string; url: string }[]
  cached?: boolean
  created_at?: string | null
  stale?: boolean
}

// 파급 시나리오 (D-038 캐시) — 저장분 즉시 표시, '다시 분석'(refresh)으로만 opus 재생성.
// 내러티브 버전이 그대로면 재분석해도 저장분 반환(백엔드 가드).
/** 통합 리포트 — 제목 리스트만(버전별), 클릭 시 리포트 페이지로. 원문은 리포트 페이지에서(D-041). */
function ReportLinkCard({ topic }: { topic: string }) {
  const to = `/report?topic=${encodeURIComponent(topic)}`
  const { data: versions = [], isLoading } = useQuery(
    apiQuery<{ id: number; title: string | null; top_pick: string | null; created_at: string }[]>({
      key: ["spine", "report", "history", topic], url: "/api/spine/report/history", params: { topic },
      staleTime: STALE.short,
    }),
  )
  return (
    <Card>
      <CardContent className="py-3">
        <div className="flex items-center gap-1.5 mb-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">통합 리포트</span>
          <Link to={to} className="ml-auto text-[11px] text-muted-foreground hover:text-foreground">리포트 페이지 →</Link>
        </div>
        {isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : versions.length === 0 ? (
          <Link to={to} className="text-xs text-muted-foreground hover:text-foreground">
            아직 통합 리포트가 없습니다 — 리포트 페이지에서 생성 →
          </Link>
        ) : (
          <ul className="space-y-1.5">
            {versions.map((v) => (
              <li key={v.id}>
                <Link to={to} className="group flex items-start gap-2">
                  <FileText className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm leading-snug group-hover:underline">{v.title || `${topic} 통합 리포트`}</div>
                    <div className="flex items-center gap-1.5 mt-0.5 text-[11px] text-muted-foreground">
                      {v.top_pick && <Badge variant="secondary" className="text-[10px] font-normal">Top-pick {v.top_pick}</Badge>}
                      <span className="tabular-nums">{v.created_at.slice(0, 10)}</span>
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

function ScenarioSection({ topic }: { topic: string }) {
  const [nonce, setNonce] = useState(0)     // >0 이면 compute 실행 (증가 시 재실행)
  const [refresh, setRefresh] = useState(false)
  const cached = useQuery(
    apiQuery<ScenarioResult>({
      key: ["spine", "narrative", "scenario", "cached", topic],
      url: `/api/spine/narrative/scenario?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short, enabled: !!topic,
    }),
  )
  const compute = useQuery(
    apiComputeQuery<ScenarioResult>({
      key: ["spine", "narrative", "scenario", "compute", topic, nonce],
      url: `/api/spine/narrative/scenario/compute?topic=${encodeURIComponent(topic)}${refresh ? "&refresh=1" : ""}`,
      enabled: nonce > 0,
    }),
  )
  const display = compute.data?.status === "ok" ? compute.data
    : cached.data?.status === "ok" ? cached.data : null
  const loading = nonce > 0 && (compute.isFetching || !compute.data)
  const failed = nonce > 0 && compute.data && compute.data.status !== "ok" && !display
  const analyze = (isRefresh: boolean) => { setRefresh(isRefresh); setNonce((n) => n + 1) }

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <Route className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">파급 시나리오</span>
          <span className="text-[11px] text-muted-foreground">사건을 1·2·3차 인과 체인으로 — 왜, 그래서 무엇</span>
          {!loading && (
            <Button size="sm" variant={display ? "outline" : "default"} className="ml-auto h-7"
              onClick={() => analyze(!!display)}>
              <Sparkles className="h-3.5 w-3.5" /> {display ? "다시 분석" : "파급 분석"}
            </Button>
          )}
        </div>
        {loading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            파급 체인을 전개하는 중… (수십 초~수 분, 심층 추론)
          </div>
        )}
        {failed && <EmptyState message="파급 분석을 생성하지 못했습니다 — 잠시 후 다시 시도." />}
        {display?.answer && (
          <Card className="bg-[color-mix(in_srgb,var(--primary)_5%,var(--card))]">
            <CardContent className="py-3 space-y-3">
              <Markdown>{display.answer}</Markdown>
              {display.beneficiaries?.length > 0 && (
                <div className="border-t pt-3">
                  <ScenarioBeneficiaries items={display.beneficiaries} event={topic} />
                </div>
              )}
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground/70 border-t pt-2">
                {display.cached && display.created_at
                  ? <span>저장분 {display.created_at.slice(0, 10)}</span>
                  : <span>방금 분석</span>}
                {display.stale && <span className="text-primary">· 내러티브 갱신됨 — 다시 분석 권장</span>}
              </div>
            </CardContent>
          </Card>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 인과 체인 구조 뷰 (그래프에서 조회) ---------- */

interface CausalEdge {
  from: string; from_type: string | null; from_id?: number; to: string; to_type: string | null; to_id?: number
  rel: string; mechanism: string | null; orientation: string | null
  reference_period: string | null; confidence: number | null
  effect_direction?: string | null; effect_strength?: string | null
  corroborated_by?: number; contested?: boolean; promoted_knowledge_id?: number | null
  id?: number; source_status?: SourceStatus | null   // 출처 검증 (D-204)
  obs_confirmed?: boolean
}
interface CausalGraph { nodes: { name: string; type: string }[]; edges: CausalEdge[] }

const NODE_LABEL: Record<string, string> = {
  company: "기업", sector: "섹터", theme: "테마", person: "인물",
  macro: "매크로", policy: "정책", event: "사건",
}
const ORIENT: Record<string, { label: string; cls: string }> = {
  past: { label: "회고", cls: "text-muted-foreground" },
  current: { label: "현재", cls: "text-foreground" },
  forward: { label: "전망", cls: "text-hypothesis" },
}
const ORIENT_ORDER: Record<string, number> = { past: 0, current: 1, forward: 2 }

function NodeChip({ name, type, id }: { name: string; type: string | null; id?: number }) {
  const cls = "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs"
  const inner = (
    <>
      {type && <span className="text-[9px] text-muted-foreground">{NODE_LABEL[type] ?? type}</span>}
      <span className="font-medium">{name}</span>
    </>
  )
  // 온톨로지 그래프의 해당 노드로 딥링크 (?focus=<id> — WorldviewPage가 그 노드에 초점)
  return id != null ? (
    <Link to={`/knowledge/ontology?focus=${id}`} title="온톨로지 그래프에서 이 노드 보기"
      className={cn(cls, "hover:border-primary hover:bg-primary/5 transition-colors")}>
      {inner}
    </Link>
  ) : (
    <span className={cls}>{inner}</span>
  )
}

function CausalChain({ narrativeId }: { narrativeId: number }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<CausalGraph>({
      key: ["spine", "narrative", "causal", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/causal`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-24 w-full rounded-card" />
  if (isError) return null   // 본문은 이미 노출됨 — 구조 뷰만 조용히 생략

  const edges = [...(data?.edges ?? [])].sort(
    (a, b) => (ORIENT_ORDER[a.orientation ?? ""] ?? 1) - (ORIENT_ORDER[b.orientation ?? ""] ?? 1),
  )

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Workflow className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">인과 구조</span>
          <span className="text-[11px] text-muted-foreground">시간순 · 원인 → 결과 · 화살표 색=방향(<span className="text-up-ink">정+</span>/<span className="text-down-ink">부−</span>), 굵기=효과 크기</span>
        </div>
        {edges.length === 0 ? (
          <EmptyState message="인과 구조가 아직 추출되지 않았습니다 — 재생성 시 그래프에 쌓입니다." />
        ) : (
          <ul className="space-y-1.5">
            {edges.map((e, i) => {
              const o = ORIENT[e.orientation ?? ""]
              const benefit = e.rel === "BENEFITS_FROM"
              return (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-sm">
                  <NodeChip name={e.from} type={e.from_type} id={e.from_id} />
                  <span className={cn("inline-flex items-center gap-0.5 text-[10px]",
                    benefit ? "text-primary" : "text-muted-foreground")}>
                    <EdgeArrow edge={e} />
                    {benefit ? "수혜" : "인과"}
                    {o && <span className={cn("ml-0.5", o.cls)}>· {o.label}</span>}
                  </span>
                  <NodeChip name={e.to} type={e.to_type} id={e.to_id} />
                  {(e.corroborated_by ?? 0) >= 2 && (
                    <Badge variant="outline" className="text-[9px] font-normal text-primary border-primary/40">
                      {e.corroborated_by}개 내러티브 확인
                    </Badge>
                  )}
                  {e.contested && (
                    <Badge variant="destructive" className="text-[9px] font-normal">상충</Badge>
                  )}
                  {e.promoted_knowledge_id && (
                    <Badge variant="secondary" className="text-[9px] font-normal">승격된 지식</Badge>
                  )}
                  {e.obs_confirmed && (
                    <Badge variant="outline" className="text-[9px] font-normal text-up-ink border-up/40" title="추적 질문의 실적 관측이 이 인과를 확증">
                      관측 확증
                    </Badge>
                  )}
                  <EdgeSourceBadge edgeId={e.id} status={e.source_status} />
                  {e.mechanism && (
                    <span className="text-[11px] text-muted-foreground w-full pl-1">↳ {e.mechanism}</span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- 메르 모드 (순회 top-1 경로 정박 서사, Phase 2 §2-2) ---------- */

interface MerNarrativeResponse {
  status: string
  narrative: string | null
  path: { nodes: { name: string; type: string }[] } | null
  stale: boolean
}

function MerNarrativeCard({ topic }: { topic: string }) {
  const qc = useQueryClient()
  const cachedMer = useQuery(
    apiQuery<MerNarrativeResponse>({
      key: ["spine", "narrative", "mer", topic],
      url: `/api/spine/narrative/mer?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short,
    }),
  )
  const freshMer = useQuery(
    apiComputeQuery<MerNarrativeResponse>({
      key: ["spine", "narrative", "mer", topic, "compute"],
      url: `/api/spine/narrative/mer/compute?topic=${encodeURIComponent(topic)}`,
      enabled: !!cachedMer.data?.stale,
    }),
  )
  useEffect(() => {
    if (freshMer.data?.status === "fresh") {
      qc.invalidateQueries({ queryKey: ["spine", "narrative", "mer", topic] })
    }
  }, [freshMer.data?.status, topic, qc])
  const m = freshMer.data ?? cachedMer.data
  const generating = freshMer.isFetching

  if (cachedMer.isLoading) return <Skeleton className="h-40 w-full rounded-card" />
  if (!m || !m.narrative) {
    return <EmptyState message="아직 순회 가능한 인과 경로가 없습니다 — 인과가 더 쌓이면 나타납니다." />
  }

  return (
    <div className="space-y-2">
      {generating && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          인과 체인을 서사로 엮는 중…
        </div>
      )}
      <Card className="bg-[color-mix(in_srgb,var(--primary)_6%,var(--card))]">
        <CardContent className="py-3 space-y-3">
          <p className="text-sm leading-relaxed">{m.narrative}</p>
          {m.path && (
            <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t">
              {m.path.nodes.map((nd, j) => (
                <span key={j} className="flex items-center gap-1.5">
                  <span className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs">
                    <span className="text-[9px] text-muted-foreground">{NODE_LABEL[nd.type] ?? nd.type}</span>
                    <span className="font-medium">{nd.name}</span>
                  </span>
                  {j < m.path!.nodes.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ---------- 근본 원인 → 수혜 경로 (전역 그래프 순회, Phase 2 §2-1) ---------- */

interface ChainPath {
  nodes: { name: string; type: string }[]
  edges: CausalEdge[]
  path_confidence: number
  reaches_sector: boolean
}
interface ChainResponse { status: string; paths: ChainPath[] }

// 인과 링크 화살표 — 방향(색: 정+ 빨강 / 부− 파랑, D-065 견고 축)·효과 크기(굵기, D-066 보조 축).
function EdgeArrow({ edge }: { edge?: CausalEdge }) {
  const dir = edge?.effect_direction
  const str = edge?.effect_strength
  const color = dir === "positive" ? "text-up-ink" : dir === "negative" ? "text-down-ink" : "text-muted-foreground"
  const size = str === "strong" ? "h-4 w-4" : str === "weak" ? "h-2.5 w-2.5" : "h-3 w-3"
  const dirLabel = dir === "positive" ? "정(+) 늘림" : dir === "negative" ? "부(−) 줄임" : "방향 미상"
  const title = str && str !== "unknown" ? `${dirLabel} · 효과 ${str}` : dirLabel
  return (
    <span title={title} className="inline-flex shrink-0">
      <ArrowRight className={cn(size, color)} />
    </span>
  )
}

function ChainPaths({ narrativeId }: { narrativeId: number }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<ChainResponse>({
      key: ["spine", "narrative", "chain", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/chain`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-20 w-full rounded-card" />
  // 엣지 부족(순회 불가)이거나 실패 — 섹션 자체를 조용히 숨김 (5-state: Empty/Error)
  if (isError || !data || data.status !== "ok" || data.paths.length === 0) return null

  return (
    <Card>
      <CardContent className="py-3 space-y-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Route className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">근본 원인 → 수혜 경로</span>
          <span className="text-[11px] text-muted-foreground">전역 인과 그래프 순회</span>
        </div>
        <div className="text-[10px] text-muted-foreground">
          화살표 색 = 효과 방향(<span className="text-up-ink">정+</span> 늘림 / <span className="text-down-ink">부−</span> 줄임), 굵기 = 효과 크기
        </div>
        <ul className="space-y-2.5">
          {data.paths.map((p, i) => (
            <li key={i} className="flex flex-wrap items-center gap-1.5 text-sm">
              {p.nodes.map((n, j) => {
                const isRoot = j === 0
                const isBeneficiary = j === p.nodes.length - 1 && p.reaches_sector
                return (
                  <span key={j} className="flex items-center gap-1.5">
                    <span className={cn(
                      "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs",
                      isRoot && "border-hypothesis/50 bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]",
                      isBeneficiary && "border-primary/50 bg-[color-mix(in_srgb,var(--primary)_8%,var(--card))]",
                    )}>
                      <span className="text-[9px] text-muted-foreground">{NODE_LABEL[n.type] ?? n.type}</span>
                      <span className="font-medium">{n.name}</span>
                    </span>
                    {j < p.nodes.length - 1 && <EdgeArrow edge={p.edges[j]} />}
                  </span>
                )
              })}
              <Badge variant="outline" className="text-[9px] font-normal text-muted-foreground ml-1">
                경로 신뢰도 {(p.path_confidence * 100).toFixed(0)}%
              </Badge>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

/* ---------- 딛고 선 지식 (내러티브↔지식 루프, Phase 2 §2-5) ---------- */

interface GroundingItem {
  knowledge_id: number; statement: string; epistemic_status: string; falsifiers: string[]
}
interface GroundingResponse { status: string; grounding: GroundingItem[] }

function Grounding({ narrativeId }: { narrativeId: number }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<GroundingResponse>({
      key: ["spine", "narrative", "grounding", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/grounding`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-16 w-full rounded-card" />
  if (isError) return <p role="alert" className="text-sm text-destructive">지식 연결을 불러오지 못했습니다.</p>
  if (!data || data.status !== "ok" || data.grounding.length === 0) return <EmptyState message="저장된 지식 연결이 없습니다." />

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5">
          <Anchor className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">이 서사가 딛고 선 지식</span>
          <span className="text-[11px] text-muted-foreground">{data.grounding.length}건</span>
        </div>
        <ul className="space-y-2">
          {data.grounding.map((g) => (
            <li key={g.knowledge_id} className="text-sm space-y-0.5">
              <p>{g.statement}</p>
              {g.falsifiers.length > 0 && (
                <div className="text-[11px] text-muted-foreground">
                  흔들릴 조건: {g.falsifiers.join(" · ")}
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

/* ---------- 공유 내러티브 (같은 그래프의 다른 서브그래프, Phase 2 §2-4 머지) ---------- */

interface RelatedNarrative {
  narrative_id: number; topic: string; title: string | null; shared_nodes: string[]
}
interface RelatedResponse { status: string; related: RelatedNarrative[] }

function RelatedNarratives({ narrativeId }: { narrativeId: number }) {
  const { data, isLoading, isError } = useQuery(
    apiQuery<RelatedResponse>({
      key: ["spine", "narrative", "related", narrativeId],
      url: `/api/spine/narrative/${narrativeId}/related`,
      staleTime: STALE.short,
    }),
  )
  if (isLoading) return <Skeleton className="h-16 w-full rounded-card" />
  if (isError || !data || data.status !== "ok" || data.related.length === 0) return null

  return (
    <section className="space-y-1" data-related>
      <h2 className="border-b pb-1 text-sm font-semibold">관련 서사</h2>
      <ul className="divide-y">
        {data.related.map((r) => (
          <li key={r.narrative_id} className="py-2">
            <p className="text-caption text-muted-foreground">{r.topic} · 공유 {r.shared_nodes.length}</p>
            <Link to={`/narrative?topic=${encodeURIComponent(r.topic)}`} className="line-clamp-2 text-sm hover:underline" title={`공유 노드: ${r.shared_nodes.join(" · ")}`}>{r.title ?? r.topic}</Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
