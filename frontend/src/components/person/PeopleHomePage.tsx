import { useState, type FormEvent, type ReactNode } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { followEntity, spineKeys } from "@/api/spine"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import FilterChips from "@/components/shared/FilterChips"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { PageContainer } from "@/components/shared/PageContainer"
import { SummaryStrip, SummaryStripSkeleton } from "@/components/industry/SummaryStrip"
import PeopleDirectoryPage from "@/components/person/PeopleDirectoryPage"
import { usePeopleHome } from "@/hooks/usePeople"
import { RoleChip } from "@/components/person/RoleChip"
import { PREMISE_STATUS, ROLE_LABEL, ROLE_ORDER, personPath, roleFilter } from "@/lib/person"
import { cn } from "@/lib/utils"
import { formatNumber } from "@/utils/format"
import type { PeopleHome, PeopleHomeRow, PersonRole, PersonRoleName, RecordedPerson } from "@/types"

/**
 * /people — 탐색 › 인물 (ia-redesign §4.23.4 A, 시안 Explore-People).
 * 요약(팔로우·기록이 있는 인물·언급된 인물) → 역할 칩 → 팔로우 | 기록이 있는 인물(전제 원장을 사람 단위로) → 이번 주 언급이 는 인물.
 * 같은 사람의 다른 이름은 서버가 자동으로 묶어 한 사람으로 센다(사용자 화면에 이름 정리 없음). 역할은 자동 분류, 못 정하면 칩 없음.
 * URL: role(policy·executive·guru) · view=all(전체 목록, 옛 디렉토리) · q(이름 검색 → 전체 목록).
 * 폰에서는 팔로우·기록이 있는 인물 두 목록만(§4.23.4 F).
 */
export default function PeopleHomePage() {
  const [params] = useSearchParams()
  if (params.get("view") === "all") return <PeopleDirectoryPage />
  return <PeopleHomeView />
}

const signed = (d: number) => `${d > 0 ? "+" : ""}${formatNumber(d)}`
const deltaTone = (d: number) => d > 0 ? "text-up-ink" : d < 0 ? "text-down-ink" : "text-muted-foreground"
const mmdd = (s: string | null) => s ? `${s.slice(5, 7)}/${s.slice(8, 10)}` : ""

function PeopleHomeView() {
  const q = usePeopleHome()
  const [params, setParams] = useSearchParams()
  const role = roleFilter(params.get("role"))
  const setRole = (v: string) => setParams(p => { const n = new URLSearchParams(p); if (v === "all") n.delete("role"); else n.set("role", v); return n }, { replace: true })
  const d = q.data
  return (
    <PageContainer>
      <PeopleHead />
      {q.isPending ? <PeopleHomeSkeleton />
        : q.isError || !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />
        : <PeopleHomeBody d={d} role={role} onRole={setRole} />}
    </PageContainer>
  )
}

function PeopleHead() {
  const navigate = useNavigate()
  const [text, setText] = useState("")
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const v = text.trim()
    if (v) navigate(`/people?view=all&q=${encodeURIComponent(v)}`)
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <h1 className="text-page font-semibold">인물</h1>
      <form onSubmit={submit} className="ml-auto w-full sm:w-72" role="search">
        <Input value={text} onChange={e => setText(e.target.value)} placeholder="인물 이름 검색" aria-label="인물 이름 검색" className="h-9" />
      </form>
    </div>
  )
}

function PeopleHomeBody({ d, role, onRole }: { d: PeopleHome; role: PersonRoleName | "all"; onRole: (v: string) => void }) {
  const pass = (r: PersonRole | null) => role === "all" || r?.role === role
  const followed = d.followed.filter(r => pass(r.role))
  const recorded = d.recorded.filter(r => pass(r.role))
  const rising = d.rising.filter(r => pass(r.role))
  const s = d.summary
  return <>
    <SummaryStrip label="인물 요약" cells={[
      { label: "팔로우", value: `${formatNumber(s.followed)}명`, sub: `이번 주 언급 ${formatNumber(s.followed_mentions_7d)}건` },
      { label: "기록이 있는 인물", value: `${formatNumber(s.recorded_people)}명`, sub: `전제 ${formatNumber(s.premises)}개` },
      { label: "언급된 인물", value: `${formatNumber(s.mentioned)}명`, sub: <Link to="/people?view=all" className="hover:text-foreground hover:underline">2건 이상 {formatNumber(s.mentioned_2plus)}명 ›</Link> },
    ]} cols={3} />
    <div className="flex flex-wrap items-center gap-1.5" data-smoke="role-chips">
      <FilterChips value={role} onChange={onRole} options={[{ value: "all", label: `전체 ${formatNumber(d.role_counts.all ?? 0)}` },
        ...ROLE_ORDER.map(k => ({ value: k, label: `${ROLE_LABEL[k]} ${formatNumber(d.role_counts[k] ?? 0)}` }))]} />
      <InfoTip label="역할 설명">정책은 기관 사전(연준·재무부·대통령실·한국은행 등), 경영자는 컨콜 화자 직함과 사람 사전, 구루는 전제 원장·메모 저자로 자동 분류합니다. 정하지 못한 사람에게는 칩을 붙이지 않습니다.</InfoTip>
    </div>
    <div className="grid gap-4 md:grid-cols-2">
      <FollowedCard rows={followed} total={d.summary.followed} />
      <RecordedCard rows={recorded} status={d.recorded_status} />
    </div>
    <div className="max-md:hidden"><RisingCard rows={rising} mentioned2={s.mentioned_2plus} /></div>
  </>
}

function CardHead({ title, note, info, action }: { title: string; note?: ReactNode; info?: ReactNode; action?: ReactNode }) {
  return <header className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b px-4 py-3">
    <h2 className="text-section font-semibold">{title}</h2>
    {note && <span className="text-caption text-muted-foreground">{note}</span>}
    {info && <span className="self-center"><InfoTip label={`${title} 설명`}>{info}</InfoTip></span>}
    {action && <span className="ml-auto text-sm">{action}</span>}
  </header>
}

function FollowedCard({ rows, total }: { rows: PeopleHomeRow[]; total: number }) {
  return <Card className="gap-0 py-0" aria-label="팔로우" data-smoke="followed">
    <CardHead title="팔로우" note={`${formatNumber(total)}명 · 이번 주 언급순`}
      action={total > 0 ? <Link to="/feed?channel_type=people" className="hover:underline">피드에서 팔로우 인물 글만 보기 ›</Link> : undefined} />
    {rows.length === 0 ? <p className="px-4 py-6 text-sm text-muted-foreground">{total === 0 ? "아직 팔로우한 인물이 없습니다. 아래 이번 주 언급이 는 인물에서 팔로우할 수 있습니다." : "이 역할의 팔로우 인물이 없습니다."}</p>
      : <ul className="divide-y px-4">{rows.map(r => <li key={r.entity_id} className="space-y-1 py-2.5" data-person-row>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Link to={personPath(r.entity_id)} className="font-semibold hover:underline">{r.name}</Link>
          <RoleChip role={r.role} />
          {r.top_stocks.map(s => <Badge key={s} variant="outline" className="h-5 rounded-none px-1.5 text-[11px] font-normal text-muted-foreground">{s}</Badge>)}
          <span className="ml-auto whitespace-nowrap font-mono text-caption tabular-nums text-muted-foreground">7일 {formatNumber(r.mentions_7d)}건 <span className={deltaTone(r.delta_7d)}>{signed(r.delta_7d)}</span></span>
        </div>
        {r.last_doc_title && <p className="truncate text-caption text-muted-foreground">
          최근 언급 — {r.last_doc_id ? <Link to={`/doc/${r.last_doc_id}`} className="hover:text-foreground hover:underline">{r.last_doc_title}</Link> : r.last_doc_title}
          <span className="ml-1 font-mono tabular-nums">{mmdd(r.last_doc_at)}</span>
        </p>}
      </li>)}</ul>}
  </Card>
}

function RecordedCard({ rows, status }: { rows: RecordedPerson[]; status: "ok" | "error" }) {
  return <Card className="gap-0 py-0" aria-label="기록이 있는 인물" data-smoke="recorded">
    <CardHead title="기록이 있는 인물" info="지금은 매크로 › 구루 전제 원장의 전제를 사람 단위로 묶어 보여 줍니다. 판정은 매크로와 같은 규칙입니다. '지지'는 지금 숫자가 전제와 맞는다는 뜻이지 증명됐다는 뜻이 아닙니다."
      action={<Link to="/home/macro#now-premises" className="hover:underline">구루 전체 원장 ›</Link>} />
    {status === "error" ? <div className="px-4 py-3"><ErrorState message="전제 원장을 불러오지 못했습니다." /></div>
      : rows.length === 0 ? <p className="px-4 py-6 text-sm text-muted-foreground">이 역할의 기록이 있는 인물이 없습니다.</p>
      : <ul className="divide-y px-4">{rows.map(r => <li key={r.entity_id ?? r.name} className="space-y-1.5 py-2.5" data-recorded-row>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {r.entity_id ? <Link to={personPath(r.entity_id)} className="font-semibold hover:underline">{r.name}</Link>
            : <span className="font-semibold">{r.name}</span>}
          <RoleChip role={r.role} />
          <span className="text-caption text-muted-foreground">{r.entity_id ? `언급 ${formatNumber(r.doc_count)}건` : "인물 없음"} · 전제 {r.premises.length}</span>
        </div>
        <ul className="space-y-1">{r.premises.map(p => {
          const st = PREMISE_STATUS[p.status ?? "none"]
          return <li key={p.key} className="flex items-start gap-2 text-sm">
            <span className="min-w-0 flex-1">{p.claim}</span>
            <Badge variant="outline" className={cn("shrink-0 rounded-none font-normal", st.cls)}>{st.label}</Badge>
          </li>
        })}</ul>
      </li>)}</ul>}
  </Card>
}

function RisingCard({ rows, mentioned2 }: { rows: PeopleHomeRow[]; mentioned2: number }) {
  const qc = useQueryClient()
  const follow = useMutation({
    mutationFn: (r: PeopleHomeRow) => followEntity({ entity_id: r.entity_id }),
    onSuccess: (_d, r) => {
      toast.success(`'${r.name}' 팔로우`)
      void qc.invalidateQueries({ queryKey: ["spine", "people"] })
      void qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })
  return <Card className="gap-0 py-0" aria-label="이번 주 언급이 는 인물" data-smoke="rising">
    <CardHead title="이번 주 언급이 는 인물" info="팔로우하지 않은 사람 중 최근 7일 언급이 그 전 7일보다 많이 는 순서입니다."
      action={<Link to="/people?view=all" className="hover:underline">전체 목록 {formatNumber(mentioned2)}명 ›</Link>} />
    {rows.length === 0 ? <p className="px-4 py-6 text-sm text-muted-foreground">이번 주 언급이 는 인물이 없습니다.</p>
      : <ul className="grid gap-x-8 px-4 md:grid-cols-2">{rows.map(r => <li key={r.entity_id} className="flex items-center gap-3 border-b py-2.5" data-rising-row>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2">
            <Link to={personPath(r.entity_id)} className="font-semibold hover:underline">{r.name}</Link>
            <RoleChip role={r.role} />
          </div>
          {r.last_doc_title && <p className="truncate text-caption text-muted-foreground">{r.last_doc_title}</p>}
        </div>
        <span className="whitespace-nowrap font-mono text-caption tabular-nums">{formatNumber(r.mentions_7d)}건 <span className={deltaTone(r.delta_7d)}>{signed(r.delta_7d)}</span></span>
        <Button size="xs" variant="outline" disabled={follow.isPending} onClick={() => follow.mutate(r)}>팔로우</Button>
      </li>)}</ul>}
  </Card>
}

function PeopleHomeSkeleton() {
  return <div className="space-y-3" role="status" aria-label="인물 불러오는 중">
    <SummaryStripSkeleton />
    <Skeleton className="h-7 w-72" />
    <div className="grid gap-4 md:grid-cols-2">
      {[0, 1].map(i => <div key={i} className="space-y-3 border p-4">{Array.from({ length: 6 }, (_, j) => <Skeleton key={j} className="h-10 w-full" />)}</div>)}
    </div>
  </div>
}
