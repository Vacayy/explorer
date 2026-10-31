// 관리자 '관측' 탭 (docs/specs/observability.md, D-283) — 잘 도는가 · 얼마나 드는가 · 무엇을 쓰는가 · 도움이 되는가.
// 섹션 하나에 카드 하나, 안은 소제목과 불릿(실적 시즌 화면과 같은 형식). 데이터는 GET /api/spine/admin/observe(LLM 0).
import { useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { apiQuery, STALE } from "@/api/query"
import { QueryState } from "@/components/shared/QueryState"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Bullets, Cols, H3, Meta, Section } from "@/components/follow/season/seasonUi"
import { formatNumber } from "@/utils/format"
import type { ObserveSummary } from "@/types"

const ACTION_KO: Record<string, string> = {
  "reaction.make": "반응 정리 만들기", "expectation.make": "기대 정리 만들기", "digest.make": "핵심 정리 만들기",
  "transcript.check": "최근 발표 조사", "transcript.collect": "종목 수집", "prices.collect": "시세 갱신",
  "overview.make": "기업 개요 만들기", "core.pin": "핵심 고정", "core.unpin": "핵심 해제", "save": "저장",
  "study.add": "스터디 추가", "chat.ask": "채팅 질문",
}
const usd = (v: number | null | undefined) => v == null ? "-" : `$${v.toFixed(v >= 100 ? 0 : 2)}`
const pct = (v: number | null | undefined) => v == null ? "" : `${v > 0 ? "+" : ""}${v}%`
const dwell = (ms: number | null) => ms == null ? "-" : ms >= 60_000 ? `${Math.floor(ms / 60_000)}분 ${Math.round((ms % 60_000) / 1000)}초` : `${Math.round(ms / 1000)}초`

export function ObservePanel() {
  const q = useQuery(apiQuery<ObserveSummary>({ key: ["spine", "admin", "observe"], url: "/api/spine/admin/observe", staleTime: STALE.short }))
  return (
    <QueryState query={q} isEmpty={() => false} loading={<div className="space-y-3"><Skeleton className="h-24 w-full rounded-xl" /><Skeleton className="h-72 w-full rounded-xl" /></div>}>
      {(d) => <Body d={d} />}
    </QueryState>
  )
}

function Body({ d }: { d: ObserveSummary }) {
  const t = d.jobs.total
  const rate = t.runs ? (t.ok / t.runs) * 100 : 0
  const problems = d.jobs.streaks.length + d.jobs.failing.length + d.jobs.chronic.length
  const g = d.value.expectation_grades
  return (
    <div className="space-y-4">
      <Section title="이번 주 한눈에" note={`최근 ${d.days}일 · 지난 기간 대비`}>
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
          <Glance q="잘 도는가" a={`정기 작업 ${rate.toFixed(1)}% 성공`} sub={`${formatNumber(t.runs)}회 중 오류 ${t.err} · 부분 ${t.partial} · 지금 문제 ${problems}건`} />
          <Glance q="얼마나 드는가" a={<>LLM {usd(d.costs.usd)} {d.costs.change_pct != null && <span className={d.costs.change_pct > 0 ? "text-up" : "text-down"}>{pct(d.costs.change_pct)}</span>}</>}
            sub={d.costs.by_job[0] ? `지난 기간 ${usd(d.costs.prev_usd)} · ${d.costs.by_job[0].name}이 ${d.costs.by_job[0].share}%` : "기록 없음"} />
          <Glance q="무엇을 쓰는가" a={d.usage.visits ? `화면 방문 ${d.usage.visits}회` : "수집 중"}
            sub={d.usage.visits ? d.usage.screens.slice(0, 3).map((s) => s.name).join(" · ") : "사용 기록이 쌓이면 표시합니다"} />
          <Glance q="도움이 되는가" a={g.hit + g.underweighted + g.noise + g.missed ? `기대 맞힘 ${g.hit}` : "수집 중"}
            sub={`덜 봄 ${g.underweighted} · 과하게 봄 ${g.noise} · 못 봄 ${g.missed}`} />
        </div>
      </Section>
      <Cols>
        <Reliability d={d} />
        <Costs d={d} />
      </Cols>
      <Cols>
        <Usage d={d} />
        <Value d={d} />
      </Cols>
    </div>
  )
}

function Glance({ q, a, sub }: { q: string; a: React.ReactNode; sub: string }) {
  return <div className="flex flex-col gap-0.5"><span className="text-caption text-muted-foreground">{q}</span><span className="font-semibold">{a}</span><span className="text-caption text-muted-foreground">{sub}</span></div>
}

function Reliability({ d }: { d: ObserveSummary }) {
  const j = d.jobs
  const items = [
    ...j.streaks.map((s) => <><b>{s.name}</b> 연속 <b>{s.streak}</b>회 실패 <Badge variant="outline" className="text-down">고칠 것</Badge><span className="block text-caption text-muted-foreground">{s.last}</span></>),
    ...j.failing.map((f) => <><b>{f.name}</b> {f.n}회 중 <b>{f.err}</b>회 실패{f.last && <span className="block text-caption text-muted-foreground">{f.last}</span>}</>),
    ...j.chronic.map((c) => <><b>{c.name}</b> 최근 5회 모두 부분 성공 <Badge variant="outline" className="text-hypothesis">만성</Badge></>),
    ...d.api.worst_errors.map((a) => <><span className="font-mono text-caption">{a.endpoint}</span> 5xx {a.errors_5xx}/{a.count}건 ({a.err_rate}%)</>),
    ...d.client_errors.map((c) => <>화면 API 오류 <span className="font-mono text-caption">{c.endpoint}</span>{c.field && ` · ${c.field}`} ({c.kind} {c.count}회)</>),
    ...d.freshness.map((f) => <>데이터 신선도: {f.label} — {f.detail}</>),
  ]
  return (
    <Section title="잘 도는가">
      <H3>지금 문제 {items.length > 0 && <Badge variant="outline" className="ml-1 text-down">{items.length}건</Badge>}</H3>
      {items.length ? <Bullets items={items} /> : <Meta>지금 문제가 없습니다.</Meta>}
      <H3>API</H3>
      {d.api.requests ? (
        <Bullets items={[
          <>요청 {formatNumber(d.api.requests)}건 · 5xx {d.api.errors_5xx}건{d.api.since && <span className="text-muted-foreground"> · {d.api.since.slice(5, 10)}부터</span>}</>,
          ...d.api.slowest.slice(0, 3).map((a) => <>느린 API <span className="font-mono text-caption">{a.endpoint}</span> p95 ≤{formatNumber(a.p95_ms ?? 0)}ms · 최대 {formatNumber(a.max_ms)}ms ({a.count}건)</>),
        ]} />
      ) : <Meta>API 요청 집계가 쌓이면 응답시간·5xx를 보입니다.</Meta>}
      <Collapsible>
        <CollapsibleTrigger className="text-caption text-muted-foreground hover:text-foreground">작업별 성공률 펼치기 ▸</CollapsibleTrigger>
        <CollapsibleContent>
          <Table className="mt-2 text-xs">
            <TableHeader><TableRow><TableHead>작업</TableHead><TableHead className="text-right">실행</TableHead><TableHead className="text-right">오류</TableHead><TableHead className="text-right">부분</TableHead><TableHead className="text-right">평균</TableHead></TableRow></TableHeader>
            <TableBody>{j.table.map((r) => (
              <TableRow key={r.job}><TableCell>{r.name}</TableCell><TableCell className="text-right tabular-nums">{r.n}</TableCell>
                <TableCell className="text-right tabular-nums">{r.err || ""}</TableCell><TableCell className="text-right tabular-nums">{r.part || ""}</TableCell>
                <TableCell className="text-right tabular-nums">{r.avg_ms != null ? `${(r.avg_ms / 1000).toFixed(1)}초` : "-"}</TableCell></TableRow>
            ))}</TableBody>
          </Table>
        </CollapsibleContent>
      </Collapsible>
    </Section>
  )
}

function Costs({ d }: { d: ObserveSummary }) {
  const c = d.costs
  return (
    <Section title="얼마나 드는가" note="LLM 비용(원장 기준)">
      <div className="h-36">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={c.daily.map((x) => ({ ...x, label: x.day.slice(5).replace("-", "/") }))} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} interval={2} />
            <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} tickFormatter={(v) => `$${v}`} />
            <Tooltip formatter={(v) => usd(typeof v === "number" ? v : null)} labelFormatter={(l) => String(l)} />
            <Bar dataKey="usd" name="비용" fill="var(--primary)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <H3>작업별 · 최근 {d.days}일</H3>
      <Table className="text-xs">
        <TableHeader><TableRow><TableHead>작업</TableHead><TableHead className="text-right">비용</TableHead><TableHead className="text-right">비중</TableHead><TableHead className="text-right">호출</TableHead><TableHead className="text-right">캐시 적중</TableHead><TableHead className="text-right">실패</TableHead></TableRow></TableHeader>
        <TableBody>{c.by_job.map((r) => (
          <TableRow key={r.job}><TableCell>{r.name}</TableCell><TableCell className="text-right tabular-nums">{usd(r.usd)}</TableCell>
            <TableCell className="text-right tabular-nums">{r.share}%</TableCell><TableCell className="text-right tabular-nums">{formatNumber(r.calls)}</TableCell>
            <TableCell className="text-right tabular-nums">{r.cache_pct ?? "-"}%</TableCell><TableCell className="text-right tabular-nums">{r.failed || ""}</TableCell></TableRow>
        ))}</TableBody>
      </Table>
      <Meta>결과물당 비용·생성 대비 열람률은 P1 — 비중이 큰 작업은 결과를 얼마나 여는지와 같이 봐야 줄일지 판단할 수 있습니다.</Meta>
    </Section>
  )
}

function Usage({ d }: { d: ObserveSummary }) {
  const u = d.usage
  if (!u.visits) return <Section title="무엇을 쓰는가"><Meta>사용 기록 수집을 시작했습니다. 화면을 쓰면 여기에 쌓입니다{u.since ? ` (${u.since.slice(5, 10)}부터)` : ""}.</Meta></Section>
  return (
    <Section title="무엇을 쓰는가" note={`방문 ${u.visits}회 · 세션 ${u.sessions}`}>
      <H3>자주 연 화면</H3>
      <Bullets items={u.screens.slice(0, 8).map((s) => <><span className="font-mono text-caption">{s.name}</span> {s.visits}회 · 평균 {dwell(s.avg_dwell_ms)}</>)} />
      {u.paths.length > 0 && <><H3>자주 가는 경로</H3><Bullets items={u.paths.slice(0, 6).map((p) => <><span className="font-mono text-caption">{p.ref}</span> → <span className="font-mono text-caption">{p.name}</span> {p.n}회</>)} /></>}
      {u.actions.length > 0 && <><H3>핵심 동작</H3><Bullets items={[u.actions.map((a) => `${ACTION_KO[a.name] ?? a.name} ${a.n}`).join(" · ")]} /></>}
      {u.dropped.length > 0 && <><H3>지난달엔 열었는데 이번 주 안 연 화면</H3><Bullets items={[u.dropped.join(" · ")]} /></>}
    </Section>
  )
}

function Value({ d }: { d: ObserveSummary }) {
  const g = d.value.expectation_grades
  return (
    <Section title="도움이 되는가">
      <H3>시스템 판단 채점</H3>
      <Bullets items={[<>발표 전 기대: 맞힘 <b>{g.hit}</b> · 덜 봄 {g.underweighted} · 과하게 봄 {g.noise} · 못 봄 {g.missed}</>]} />
      <H3>생성물 열람</H3>
      {d.value.opens.length
        ? <Bullets items={d.value.opens.map((o) => <>{o.name} {o.n}회 열람 · {o.uniq}건</>)} />
        : <Meta>생성 대비 열람률(자동으로 만든 것 중 실제로 연 비율)과 👍/👎는 P1에서 붙입니다.</Meta>}
    </Section>
  )
}
