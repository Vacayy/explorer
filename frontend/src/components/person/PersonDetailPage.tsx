import { useEffect, type ReactNode } from "react"
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, ExternalLink, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { postJson, toApiError } from "@/api/query"
import { followEntity, spineKeys, unfollowEntity } from "@/api/spine"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { Expandable } from "@/components/shared/Expandable"
import { InfoTip } from "@/components/shared/InfoTip"
import { Markdown } from "@/components/shared/Markdown"
import { PageContainer } from "@/components/shared/PageContainer"
import { SummaryStrip, SummaryStripSkeleton } from "@/components/industry/SummaryStrip"
import { RoleChip } from "@/components/person/RoleChip"
import { usePersonDetail, usePersonResolve } from "@/hooks/usePeople"
import { attachToAi } from "@/lib/aiPanel"
import { PREMISE_STATUS, personPath, verdictSummary } from "@/lib/person"
import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/format"
import type { PersonDetail, PersonDocRow, PersonPremise, PersonProfile } from "@/types"

const SOURCE_LABEL: Record<string, string> = {
  telegram: "텔레그램", blog: "블로그", youtube: "유튜브", scrap: "스크랩", web: "웹", memo: "메모", transcript: "컨콜",
  earnings_release: "실적 발표", note: "노트", canon: "역사", dart_business: "공시",
}
const srcLabel = (s: string | null) => (s && SOURCE_LABEL[s]) || s || ""
const day = (s: string | null) => (s ?? "").slice(0, 10)
const ym = (s: string | null) => (s ?? "").slice(0, 7)
const mmdd = (s: string | null) => s ? `${s.slice(5, 7)}/${s.slice(8, 10)}` : "-"

/**
 * /person?name= — 옛 이름 주소(§10.6). 서버가 이름을 대표 인물 id로 찾아 /person/:id로 보낸다(묶인 이름도 대표로).
 */
export function PersonNameRedirect() {
  const [params] = useSearchParams()
  const name = (params.get("name") ?? "").trim()
  const q = usePersonResolve(name)
  if (!name) return <Navigate to="/people" replace />
  if (q.isPending) return <PageContainer><PersonSkeleton /></PageContainer>
  if (q.isError) return <PageContainer><ErrorState error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} /></PageContainer>
  if (q.data?.entity_id) return <Navigate to={personPath(q.data.entity_id)} replace />
  return <PageContainer><Crumb name={name} /><EmptyState message={`'${name}'(이)라는 인물을 찾지 못했습니다.`} /></PageContainer>
}

/**
 * /person/:id — 인물 상세 (ia-redesign §4.23.4 B·F, 시안 Person-Detail · Mobile-Person).
 * 머리(이름·역할·소속·묶은 이름·팔로우·이 인물로 대화) → 요약 → 기록 원장(1단계 = 구루 전제) → 본인 글 | 인용·흐름·함께 언급·내러티브·프로필.
 * 묶인 이름의 id로 오면 대표 인물 주소로 바꾼다. 프로필은 버튼으로만 만든다(열람 시 자동 생성 없음). 블록 단위 실패.
 */
export default function PersonDetailPage() {
  const { id } = useParams()
  const pid = Number(id)
  const q = usePersonDetail(pid)
  const navigate = useNavigate()
  const d = q.data
  useEffect(() => { if (d && d.entity_id !== pid) navigate(personPath(d.entity_id), { replace: true }) }, [d, pid, navigate])
  if (!Number.isFinite(pid) || pid <= 0) return <Navigate to="/people" replace />
  return <PageContainer>
    {q.isPending ? <PersonSkeleton />
      : q.isError || !d ? <><Crumb name="" /><ErrorState error={q.error} message={q.error && toApiError(q.error).status === 404 ? "이 인물을 찾지 못했습니다." : undefined} onRetry={() => void q.refetch()} retrying={q.isFetching} /></>
      : <PersonBody d={d} />}
  </PageContainer>
}

function Crumb({ name }: { name: string }) {
  return <nav aria-label="경로" className="text-caption text-muted-foreground">
    <Link to="/people" className="hover:text-foreground hover:underline">인물</Link>{name && <> › {name}</>}
  </nav>
}

function PersonBody({ d }: { d: PersonDetail }) {
  const statuses = d.premises.map(p => p.status)
  const lastCited = d.cited[0] ?? null
  return <>
    <Crumb name={d.name} />
    <PersonHead d={d} />
    <SummaryStrip label="인물 요약" cells={[
      { label: "기록", value: d.premises.length ? `전제 ${d.premises.length}` : "0", sub: d.premises.length ? verdictSummary(statuses) : "아직 기록이 없습니다" },
      { label: "본인 글", value: d.own_total ? `${d.own_source ? "메모 " : ""}${formatNumber(d.own_total)}편` : "0", sub: d.own_source ?? (d.own_total ? null : "저자 연결 없음") },
      { label: "언급", value: `${formatNumber(d.mentions.count)}건`, sub: d.mentions.first_at ? `${ym(d.mentions.first_at)} ~ ${ym(d.mentions.last_at)}` : null },
      { label: "최근 인용", value: lastCited ? mmdd(lastCited.published_at) : "-", sub: lastCited ? srcLabel(lastCited.source_type) : null },
    ]} />
    <LedgerCard d={d} />
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <div className="min-w-0 space-y-4">
        {(d.own_total > 0 || d.role?.role === "guru") && <OwnDocsCard d={d} />}
        <CitedCard d={d} />
      </div>
      <div className="min-w-0 space-y-4">
        {d.flow.length > 0 && <FlowCard d={d} />}
        <CoCard d={d} />
        <NarrativesCard d={d} />
        <ProfileCard d={d} />
      </div>
    </div>
  </>
}

function PersonHead({ d }: { d: PersonDetail }) {
  const qc = useQueryClient()
  const done = (msg: string) => {
    toast.success(msg)
    void qc.invalidateQueries({ queryKey: ["spine", "person", "id", d.entity_id] })
    void qc.invalidateQueries({ queryKey: ["spine", "people"] })
    void qc.invalidateQueries({ queryKey: spineKeys.home() })
  }
  const follow = useMutation({ mutationFn: () => followEntity({ entity_id: d.entity_id }), onSuccess: () => done(`'${d.name}' 팔로우`) })
  const unfollow = useMutation({ mutationFn: () => unfollowEntity(d.entity_id), onSuccess: () => done(`'${d.name}' 팔로우 해제`) })
  const busy = follow.isPending || unfollow.isPending
  return <header className="flex flex-wrap items-start gap-x-4 gap-y-2" data-smoke="person-head">
    <div className="min-w-0 flex-1 space-y-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h1 className="text-page font-semibold">{d.name}</h1>
        <RoleChip role={d.role} org />
      </div>
      {d.merged_names.length > 0 && <p className="text-caption text-muted-foreground" data-merged-names>
        같은 사람으로 묶은 이름: {d.merged_names.map(m => m.name).join(" · ")}
      </p>}
    </div>
    <div className="flex shrink-0 items-center gap-2">
      <Button size="sm" variant={d.following ? "outline" : "default"} disabled={busy}
        onClick={() => (d.following ? unfollow.mutate() : follow.mutate())}>{d.following ? "팔로우 중" : "팔로우"}</Button>
      <Button size="sm" variant="outline" onClick={() => attachToAi({ kind: "person", ref: String(d.entity_id), label: d.name, available: true })}>이 인물로 대화</Button>
    </div>
  </header>
}

function Block({ title, note, info, action, children, label }: { title: string; note?: ReactNode; info?: ReactNode; action?: ReactNode; children: ReactNode; label?: string }) {
  return <Card className="gap-0 py-0" aria-label={label ?? title}>
    <header className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b px-4 py-3">
      <h2 className="text-section font-semibold">{title}</h2>
      {note && <span className="text-caption text-muted-foreground">{note}</span>}
      {info && <span className="self-center"><InfoTip label={`${title} 설명`}>{info}</InfoTip></span>}
      {action && <span className="ml-auto text-sm">{action}</span>}
    </header>
    <div className="p-4">{children}</div>
  </Card>
}

function LedgerCard({ d }: { d: PersonDetail }) {
  return <Block title="기록 원장 — 지금 맞아 가나" label="기록 원장"
    info="이 사람이 한 검증 가능한 주장과 지금 판정입니다. 지금은 매크로 › 구루 전제 원장의 전제를 사람 단위로 보여 줍니다. 판정은 지표 규칙으로 정하고, '지지'는 지금 숫자가 맞는다는 뜻이지 증명됐다는 뜻이 아닙니다."
    action={<Link to="/home/macro#now-premises" className="hover:underline">매크로 › 구루 전제 원장 ›</Link>}>
    {d.premises_status === "error" ? <ErrorState message="전제 원장을 불러오지 못했습니다." />
      : d.premises.length === 0 ? <p className="text-sm text-muted-foreground" data-smoke="ledger-empty">아직 기록이 없습니다.</p>
      : <>
        <div className="grid gap-3 max-md:hidden md:grid-cols-2 xl:grid-cols-3" data-smoke="ledger">{d.premises.map(p => <PremiseCard key={p.key} p={p} />)}</div>
        <div className="divide-y md:hidden" data-smoke="ledger-mobile">{d.premises.map((p, i) => <PremiseFold key={p.key} p={p} open={i === 0} />)}</div>
      </>}
  </Block>
}

function StatusBadge({ p }: { p: PersonPremise }) {
  const st = PREMISE_STATUS[p.status ?? "none"]
  return <Badge variant="outline" className={cn("shrink-0 rounded-none font-normal", st.cls)}>{st.label}</Badge>
}

function PremiseFacts({ p }: { p: PersonPremise }) {
  const co = p.co_holders
  return <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-2 gap-y-1.5 text-sm">
    {co.length > 0 && <><dt className="text-caption text-muted-foreground">같은 전제</dt><dd className="text-caption">
      {co.map((w, i) => <span key={w.label}>{i > 0 && " · "}{w.entity_id ? <Link to={personPath(w.entity_id)} className="hover:underline">{w.name ?? w.label}</Link> : w.label}</span>)}
    </dd></>}
    {p.evidence.length > 0 && <><dt className="text-caption text-muted-foreground">지금 수치</dt><dd className="tabular-nums">{p.evidence.join(" · ")}</dd></>}
    <dt className="text-caption text-muted-foreground">판정 규칙</dt><dd>{p.rule}</dd>
    {p.sources.length > 0 && <><dt className="text-caption text-muted-foreground">원문</dt><dd className="space-y-0.5">
      {p.sources.map(s => <div key={s.title}>{s.doc_id ? <Link to={`/doc/${s.doc_id}`} className="hover:underline">{s.title}</Link>
        : <a href={s.url ?? "#"} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 hover:underline">{s.title}<ExternalLink className="size-3" aria-hidden="true" /></a>}
        <span className="ml-1 font-mono text-caption tabular-nums text-muted-foreground">{s.date}</span></div>)}
    </dd></>}
  </dl>
}

function PremiseCard({ p }: { p: PersonPremise }) {
  return <article className="space-y-2 border bg-muted/30 p-3" data-premise={p.key}>
    <div className="flex flex-wrap items-center gap-1.5 text-caption text-muted-foreground">
      <Badge variant="outline" className="h-5 rounded-none px-1.5 text-[11px] font-normal">전제</Badge>
      <Badge variant="outline" className="h-5 rounded-none px-1.5 text-[11px] font-normal">지표 규칙</Badge>
      {p.said_at && <span>말한 때 <span className="font-mono tabular-nums">{p.said_at}</span></span>}
    </div>
    <div className="flex items-start gap-2"><h3 className="min-w-0 flex-1 font-semibold leading-snug">{p.claim}</h3><StatusBadge p={p} /></div>
    <PremiseFacts p={p} />
  </article>
}

function PremiseFold({ p, open }: { p: PersonPremise; open: boolean }) {
  return <Collapsible defaultOpen={open} className="py-2.5">
    <div className="flex items-start gap-2"><h3 className="min-w-0 flex-1 font-semibold leading-snug">{p.claim}</h3><StatusBadge p={p} /></div>
    <CollapsibleTrigger asChild>
      <Button variant="ghost" size="xs" className="group -ml-2 mt-1 text-muted-foreground">근거·규칙<ChevronDown className="transition-transform group-data-[state=open]:rotate-180" /></Button>
    </CollapsibleTrigger>
    <CollapsibleContent className="pt-1"><PremiseFacts p={p} /></CollapsibleContent>
  </Collapsible>
}

function DocList({ docs, source }: { docs: PersonDocRow[]; source?: boolean }) {
  return <ul className="divide-y">{docs.map(d => <li key={d.id} className="flex items-baseline gap-3 py-2 text-sm">
    <span className="shrink-0 font-mono text-caption tabular-nums text-muted-foreground">{day(d.published_at)}</span>
    {source && <span className="w-14 shrink-0 text-caption text-muted-foreground">{srcLabel(d.source_type)}</span>}
    <Link to={`/doc/${d.id}`} className="min-w-0 truncate hover:underline">{d.title}</Link>
  </li>)}</ul>
}

function OwnDocsCard({ d }: { d: PersonDetail }) {
  const shown = Math.min(d.own_docs.length, 14)
  return <Block title={d.own_source ? `본인 글 — ${d.own_source} 메모` : "본인 글"} note={d.own_total ? `${formatNumber(d.own_total)}편 · 최근 ${shown}편` : undefined}>
    {d.own_total === 0 ? <p className="text-sm text-muted-foreground">저자 연결 안 됨</p>
      : <Expandable collapsedHeight={520}><DocList docs={d.own_docs} /></Expandable>}
  </Block>
}

function CitedCard({ d }: { d: PersonDetail }) {
  return <Block title="다른 사람이 인용한 것" note={d.cited_total ? `최근 ${d.cited.length}건 · 전체 ${formatNumber(d.cited_total)}건` : undefined}
    action={d.cited_total > 0 ? <Link to={`/feed?view=documents&q=${encodeURIComponent(d.name)}`} className="hover:underline">피드에서 모두 보기 ›</Link> : undefined}>
    {d.cited.length === 0 ? <p className="text-sm text-muted-foreground">다른 글에서 언급된 적이 없습니다.</p> : <DocList docs={d.cited} source />}
  </Block>
}

function FlowCard({ d }: { d: PersonDetail }) {
  const max = Math.max(...d.flow.map(f => f.own + f.cited), 1)
  const own = d.flow.reduce((a, f) => a + f.own, 0), cited = d.flow.reduce((a, f) => a + f.cited, 0)
  return <Block title="글과 인용 흐름" note={`연도별${own ? ` · 본인 글 ${formatNumber(own)}` : ""} · 인용 ${formatNumber(cited)}`}>
    <div className="flex items-center gap-3 pb-2 text-caption text-muted-foreground">
      {own > 0 && <span className="inline-flex items-center gap-1"><span className="size-2.5 bg-foreground/70" aria-hidden="true" />본인 글</span>}
      <span className="inline-flex items-center gap-1"><span className="size-2.5 bg-muted-foreground/35" aria-hidden="true" />다른 사람의 인용</span>
    </div>
    <div className="flex h-36 items-end gap-2" role="img" aria-label={d.flow.map(f => `${f.year}년 본인 ${f.own} 인용 ${f.cited}`).join(", ")}>
      {d.flow.map(f => <div key={f.year} className="flex min-w-0 flex-1 flex-col items-center gap-1">
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{f.own + f.cited}</span>
        <div className="flex w-full max-w-12 flex-col justify-end" style={{ height: `${((f.own + f.cited) / max) * 100}px` }}>
          <div className="w-full bg-muted-foreground/35" style={{ height: `${(f.cited / max) * 100}px` }} />
          <div className="w-full bg-foreground/70" style={{ height: `${(f.own / max) * 100}px` }} />
        </div>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{f.year}</span>
      </div>)}
    </div>
  </Block>
}

function CoCard({ d }: { d: PersonDetail }) {
  return <Block title="함께 언급되는 것" note="주제·종목·인물">
    {d.co_entities.length === 0 ? <p className="text-sm text-muted-foreground">함께 언급된 것이 아직 없습니다.</p>
      : <div className="flex flex-wrap gap-1.5">{d.co_entities.map(e => {
        const to = e.link_type === "stock" ? (e.aliases ? `/analyze/${e.aliases}/summary` : `/company?name=${encodeURIComponent(e.name)}`)
          : e.link_type === "person" ? personPath(e.entity_id) : `/feed?view=documents&${e.link_type === "industry" ? "industry" : "topic"}=${encodeURIComponent(e.name)}`
        return <Badge key={`${e.entity_id}-${e.link_type}`} asChild variant="outline" className="h-7 gap-1 rounded-full px-2.5 font-normal">
          <Link to={to}>{e.name}<span className="font-mono text-[11px] tabular-nums text-muted-foreground">{e.count}</span></Link>
        </Badge>
      })}</div>}
  </Block>
}

function NarrativesCard({ d }: { d: PersonDetail }) {
  const topics = [...new Map(d.relations.filter(r => r.narrative_topic).map(r => [r.narrative_topic!, r.narrative_title])).entries()]
  return <Block title="등장하는 내러티브" note={d.relations.length ? `인과 고리 ${d.relations.length}` : undefined}>
    {topics.length === 0 ? <p className="text-sm text-muted-foreground">아직 이 인물이 끝점인 인과 고리가 없습니다.</p>
      : <ul className="space-y-1.5">{topics.map(([t, title]) => <li key={t} className="flex items-baseline gap-2 text-sm">
        <Link to={`/narrative?topic=${encodeURIComponent(t)}`} className="shrink-0 font-medium hover:underline">{t}</Link>
        {title && title !== t && <span className="min-w-0 truncate text-muted-foreground">{title}</span>}
      </li>)}</ul>}
  </Block>
}

function ProfileCard({ d }: { d: PersonDetail }) {
  const qc = useQueryClient()
  const make = useMutation({
    mutationFn: () => postJson<PersonProfile>(`/api/spine/person/${encodeURIComponent(d.name)}/profile`),
    onSuccess: (p) => {
      if (p.status === "fresh" || p.status === "cached") toast.success("프로필을 만들었습니다")
      else toast.error(p.status === "unavailable" ? "AI 엔진이 꺼져 있어 만들지 못했습니다" : "프로필을 만들지 못했습니다")
      void qc.invalidateQueries({ queryKey: ["spine", "person", "id", d.entity_id] })
    },
    onError: () => toast.error("프로필을 만들지 못했습니다"),
  })
  const p = d.profile
  return <Block title="인물 프로필" note={p?.created_at ? `AI 요약 · ${day(p.created_at)} 기준` : "AI 요약"}
    action={(!p || d.profile_stale) && d.mentions.count > 0 ? <Button size="xs" variant="outline" disabled={make.isPending} onClick={() => make.mutate()}>
      {make.isPending ? <><Loader2 className="size-3 animate-spin" />만드는 중…</> : p ? "다시 만들기" : "프로필 만들기"}</Button> : undefined}>
    {p?.digest ? <>
      {d.profile_stale && (d.new_since_profile ?? 0) > 0 && <p className="mb-2 text-caption text-chart-warning">프로필 이후 새 언급 {formatNumber(d.new_since_profile)}건</p>}
      <Expandable collapsedHeight={240}><Markdown>{p.digest}</Markdown></Expandable>
    </> : <p className="text-sm text-muted-foreground">{d.mentions.count > 0 ? "프로필이 아직 없습니다." : "언급된 글이 없어 프로필을 만들 수 없습니다."}</p>}
  </Block>
}

function PersonSkeleton() {
  return <div className="space-y-3" role="status" aria-label="인물 불러오는 중">
    <Skeleton className="h-4 w-32" /><Skeleton className="h-8 w-56" />
    <SummaryStripSkeleton />
    <Skeleton className="h-64 w-full" />
    <div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-72 w-full" /><Skeleton className="h-72 w-full" /></div>
  </div>
}
