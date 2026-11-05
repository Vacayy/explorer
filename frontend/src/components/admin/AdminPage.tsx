import type { ReactNode } from "react"
import { toast } from "sonner"
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { PageContainer } from "@/components/shared/PageContainer"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ErrorState } from "@/components/shared/ErrorState"
import { Button } from "@/components/ui/button"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Spinner } from "@/components/ui/spinner"
import { InfoTip } from "@/components/shared/InfoTip"
import { Section } from "@/components/follow/season/seasonUi"
import { ObservePanel } from "@/components/admin/ObservePanel"
import { SourcesPanel } from "@/components/admin/SourcesPanel"
import { CurationPanel } from "@/components/admin/CurationPanel"
import { CurationApplySwitch, FreshnessBadge, RunStatusBadge } from "@/components/admin/adminUi"
import { useAdminHealth, useAdminJobs, useAdminRuns, useCurationLog, useSetFlag } from "@/hooks/useAdmin"
import { useCollectRegimes } from "@/hooks/useRegimes"
import { formatKstDateTime, formatNumber, formatSeconds } from "@/utils/format"
import type { AdminJobRun } from "@/types"

/**
 * /admin — 관리자 (D-055 · ia-redesign §4.31). 보기 넷: 작업·신선도(기본) · 관측(?view=observe) · 소스(/admin/sources, §4.26) · 자동 정리(?view=curation).
 * 대메뉴가 아니다 — 상단 바 운영 상태 창·설정 메뉴에서 들어온다. 작업 시각(job_runs.ran_at)은 UTC라 KST로 바꿔 보인다.
 */
type View = "ops" | "observe" | "sources" | "curation"
const VIEW_URL: Record<View, string> = { ops: "/admin", observe: "/admin?view=observe", sources: "/admin/sources", curation: "/admin?view=curation" }

export default function AdminPage() {
  const [params] = useSearchParams()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const raw = params.get("view")
  // 옛 ?view=sources는 소스 주소로(쿼리 나머지는 버린다 — 소스 보기는 쿼리를 쓰지 않는다)
  if (pathname !== "/admin/sources" && raw === "sources") return <Navigate to="/admin/sources" replace />
  const view: View = pathname === "/admin/sources" ? "sources" : raw === "observe" ? "observe" : raw === "curation" ? "curation" : "ops"
  return (
    <PageContainer gap="sm">
      <h2 className="text-xl font-bold">관리자</h2>
      <ToggleGroup type="single" value={view} variant="outline" size="sm" className="w-fit"
        onValueChange={(v) => v && navigate(VIEW_URL[v as View], { replace: true })}>
        <ToggleGroupItem value="ops">작업·신선도</ToggleGroupItem>
        <ToggleGroupItem value="observe">관측</ToggleGroupItem>
        <ToggleGroupItem value="sources">소스</ToggleGroupItem>
        <ToggleGroupItem value="curation">자동 정리</ToggleGroupItem>
      </ToggleGroup>
      {view === "sources" ? <SourcesPanel /> : view === "observe" ? <ObservePanel /> : view === "curation" ? <CurationPanel /> : <OpsView />}
    </PageContainer>
  )
}

/** 자동 정리가 처음 도는 회차 — 실행 기록이 없을 때 이유를 한 줄로 */
const FIRST_RUN_NOTE: Record<string, string> = { auto_curation: "다음 주간 제안 스캔(일 07:20)에서 처음 돕니다" }
const NEW_JOBS = new Set(["auto_curation"])

function OpsView() {
  return (
    <div className="space-y-4">
      <NowStatus />
      <FreshnessSection />
      <CurationStage />
      <JobsSection />
      <RecollectRegimes />
      <RunsSection />
    </div>
  )
}

/** 지금 상태 3칸 — 신선도 · 작업 켜짐 · 최근 40회 오류. 칸마다 따로 실패한다 */
function NowStatus() {
  const health = useAdminHealth()
  const jobs = useAdminJobs()
  const runs = useAdminRuns(40)
  const bad = (health.data ?? []).filter(h => h.status !== "ok")
  const stale = bad.filter(h => h.status === "stale").length
  const on = (jobs.data ?? []).filter(j => j.enabled)
  const off = (jobs.data ?? []).filter(j => !j.enabled)
  const errs = (runs.data ?? []).filter(r => r.status === "error")
  const errByJob = Object.entries(errs.reduce<Record<string, number>>((a, r) => ({ ...a, [r.job]: (a[r.job] ?? 0) + 1 }), {}))
  const latest = runs.data?.[0]?.ran_at
  return (
    <Section title="지금 상태" note={latest ? `${formatKstDateTime(latest)} 기준` : undefined}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Cell label="데이터 신선도" q={health}
          value={health.data && `${health.data.length - bad.length}/${health.data.length}`}
          sub={health.data && (bad.length ? [stale && `지연 ${stale}`, bad.length - stale && `오류 ${bad.length - stale}`].filter(Boolean).join(" · ") + ` — ${bad.map(b => b.label).join(", ")}` : "모두 최신")} />
        <Cell label="작업" q={jobs}
          value={jobs.data && `${on.length}/${jobs.data.length} 켜짐`}
          sub={jobs.data && (off.length ? `꺼짐 ${off.length} — ${off.map(j => j.label).join(", ")}` : "모두 켜짐")} />
        <Cell label={`최근 실행 ${runs.data?.length ?? 40}회`} q={runs}
          value={runs.data && `오류 ${errs.length}`}
          sub={runs.data && (errByJob.length ? errByJob.map(([j, n]) => `${j} ${n}회`).join(" · ") : "오류 없음")} />
      </div>
    </Section>
  )
}

function Cell({ label, value, sub, q }: { label: string; value: ReactNode; sub: ReactNode; q: { isPending: boolean; isError: boolean } }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-caption text-muted-foreground">{label}</span>
      {q.isPending ? <Skeleton className="h-7 w-24" />
        : q.isError ? <span className="text-sm text-muted-foreground">불러오지 못했습니다</span>
        : <><span className="font-mono text-2xl font-semibold tabular-nums">{value}</span><span className="text-caption text-muted-foreground">{sub}</span></>}
    </div>
  )
}

/** 신선도 최신 시각 — 원천마다 날짜·시각·ISO가 섞여 있어 앞 16자만, T는 띄어 쓴다 */
const fmtLatest = (v: string | null) => v ? v.slice(0, 16).replace("T", " ") : "-"

function FreshnessSection() {
  const health = useAdminHealth()
  return (
    <Section title={<>데이터 신선도<InfoTip label="데이터 신선도 설명">작업이 정상 종료돼도 결과가 비거나 묵을 수 있어, 저장된 데이터의 최신 시점을 기대치와 비교합니다. ‘경고’ 항목은 홈 브리핑·텔레그램에도 표시됩니다.</InfoTip></>}
      note={health.data ? `모두 ${health.data.length}개` : undefined}>
      {health.isPending && <Skeleton className="h-48 w-full rounded-card" />}
      {health.isError && <ErrorState message="신선도 점검을 불러오지 못했습니다." onRetry={() => health.refetch()} retrying={health.isFetching} />}
      {health.data && (health.data.length === 0 ? <p className="text-sm text-muted-foreground">아직 점검할 원천이 없습니다</p> : (
        <Table className="table-fixed md:table-auto">
          <TableHeader><TableRow>
            <TableHead>데이터</TableHead><TableHead className="w-14 md:w-auto">상태</TableHead><TableHead className="hidden md:table-cell">최신</TableHead>
            <TableHead className="hidden md:table-cell">기대</TableHead><TableHead className="hidden md:table-cell">채우는 곳</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {health.data.map((h) => (
              <TableRow key={h.key}>
                <TableCell className="whitespace-normal text-sm">
                  {h.label}{h.critical && <Badge variant="outline" className="ml-1.5 text-[10px]">경고</Badge>}
                  {h.status !== "ok" && h.detail && <div className="break-all text-caption text-muted-foreground">{h.detail}</div>}
                  {/* 모바일: 최신·기대 열을 접고 이름 아래 한 줄로 */}
                  <div className="text-caption tabular-nums text-muted-foreground md:hidden">최신 {fmtLatest(h.latest)} · 기대 {h.expected ?? "-"}</div>
                </TableCell>
                <TableCell><FreshnessBadge status={h.status} /></TableCell>
                <TableCell className="hidden font-mono text-caption tabular-nums md:table-cell">{fmtLatest(h.latest)}</TableCell>
                <TableCell className="hidden text-caption tabular-nums text-muted-foreground md:table-cell">{h.expected ?? "-"}</TableCell>
                <TableCell className="hidden whitespace-normal text-caption text-muted-foreground md:table-cell">{h.owner}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ))}
    </Section>
  )
}

/** 자동 정리 단계(D-295) — 판정 기록(auto_curation, 작업 플래그)과 적용(auto_curation_apply) 두 스위치 */
function CurationStage() {
  const jobs = useAdminJobs()
  const log = useCurationLog(null, null)
  const flag = useSetFlag()
  const judge = jobs.data?.find(j => j.name === "auto_curation")
  return (
    <Section title={<>자동 정리 단계<InfoTip label="자동 정리 단계 설명">auto_curation은 별칭·노드 병합·지식 승격을 규칙으로 판정해 기록만 남깁니다(기본 켜짐). auto_curation_apply를 켜면 다음 판정부터 그대로 적용하고 정리 작업이 인박스에서 빠집니다. 판정 기록은 ‘자동 정리’ 보기에서 봅니다.</InfoTip></>}>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <FlagBox code="auto_curation" on={judge?.enabled} pending={jobs.isPending} failed={jobs.isError}>
          {judge && <Switch aria-label="자동 정리 판정 기록" checked={judge.enabled} disabled={flag.isPending}
            onCheckedChange={v => flag.mutate({ name: "auto_curation", enabled: v })} />}
        </FlagBox>
        <FlagBox code="auto_curation_apply" on={log.data?.apply_enabled} pending={log.isPending} failed={log.isError}>
          {log.data && <CurationApplySwitch enabled={log.data.apply_enabled} />}
        </FlagBox>
      </div>
    </Section>
  )
}

function FlagBox({ code, on, pending, failed, children }: { code: string; on: boolean | undefined; pending: boolean; failed: boolean; children: ReactNode }) {
  return (
    <div className="flex min-h-11 items-center gap-2 border bg-muted/40 px-3 py-2">
      <code className="truncate font-mono text-xs">{code}</code>
      {pending ? <Skeleton className="h-4 w-10" /> : failed ? <span className="text-caption text-muted-foreground">확인 안 됨</span>
        : <Badge variant="outline" className={on ? "text-fact border-fact/40 text-[10px]" : "text-muted-foreground text-[10px]"}>{on ? "켜짐" : "꺼짐"}</Badge>}
      <div className="ml-auto flex items-center">{children}</div>
    </div>
  )
}

function JobsSection() {
  const jobs = useAdminJobs()
  const flag = useSetFlag()
  return (
    <Section title={<>자동 작업<InfoTip label="자동 작업 설명">예약 작업마다 켜고 끕니다. 끄면 다음 예약 실행부터 ‘건너뜀’으로 기록됩니다. ⓘ에 하는 일과 실제로 도는 코드가 있습니다.</InfoTip></>}
      note={jobs.data ? `${jobs.data.length}개` : undefined}>
      {jobs.isPending && <Skeleton className="h-40 w-full rounded-card" />}
      {jobs.isError && <ErrorState message="작업 목록을 불러오지 못했습니다." onRetry={() => jobs.refetch()} retrying={jobs.isFetching} />}
      {jobs.data && (
        <ul className="divide-y border-t">
          {jobs.data.map((j) => (
            <li key={j.name} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                  <span className="text-sm font-medium">{j.label}</span>
                  <InfoTip label={`${j.label} 설명`}>{j.description}<br /><code className="font-mono">{j.entrypoint}</code></InfoTip>
                  <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground">{j.name}</code>
                  <RunStatusBadge status={j.last_run?.status ?? null} />
                  {NEW_JOBS.has(j.name) && <Badge variant="outline" className="text-[10px] text-hypothesis">새로</Badge>}
                </div>
                <div className="mt-0.5 break-all font-mono text-caption text-muted-foreground">
                  {j.last_run
                    ? <>최근 {formatKstDateTime(j.last_run.ran_at)}{j.last_run.duration_ms != null && ` · ${formatSeconds(j.last_run.duration_ms)}`}{j.last_run.summary && ` · ${j.last_run.summary}`}</>
                    : FIRST_RUN_NOTE[j.name] ?? "아직 실행 기록이 없습니다"}
                </div>
              </div>
              <Switch aria-label={`${j.label} 켜기`} checked={j.enabled} disabled={flag.isPending}
                onCheckedChange={(v) => flag.mutate({ name: j.name, enabled: v })} />
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function RunsSection() {
  const runs = useAdminRuns(40)
  return (
    <Section title="최근 실행 내역" note={runs.data?.length ? `최근 ${runs.data.length}회` : undefined}>
      {runs.isPending && <Skeleton className="h-40 w-full rounded-card" />}
      {runs.isError && <ErrorState message="실행 내역을 불러오지 못했습니다." onRetry={() => runs.refetch()} retrying={runs.isFetching} />}
      {runs.data && (runs.data.length === 0
        ? <p className="text-sm text-muted-foreground">아직 기록된 실행이 없습니다 — 예약 작업이 돌면 쌓입니다.</p>
        : <ul className="divide-y border-t">{runs.data.map((r, i) => <RunRow key={i} r={r} />)}</ul>)}
    </Section>
  )
}

function RunRow({ r }: { r: AdminJobRun }) {
  return (
    <li className="grid grid-cols-[auto_auto_1fr_auto] items-center gap-x-2 gap-y-0.5 py-1.5 text-caption md:grid-cols-[auto_auto_auto_1fr_auto]">
      <span className="font-mono tabular-nums text-muted-foreground">{formatKstDateTime(r.ran_at)}</span>
      <RunStatusBadge status={r.status} />
      <span className="truncate font-medium">{r.job}</span>
      <span className="order-last col-span-4 min-w-0 truncate text-muted-foreground md:order-none md:col-span-1">{r.summary}</span>
      <span className="text-right font-mono tabular-nums text-muted-foreground">{formatSeconds(r.duration_ms)}</span>
    </li>
  )
}

/**
 * 국면 이력 다시 받기 — 홈 › 매크로는 이력이 비면 자동으로 첫 수집만 한다(ia-redesign §4.28 결정 ①).
 * 사용자 화면에서 뺀 '이력 수집' 버튼이 여기로 왔다. 처음엔 전 이력, 이후엔 최근 1개월을 받는다.
 */
function RecollectRegimes() {
  const collect = useCollectRegimes()
  const run = () => collect.mutate(undefined, {
    onSuccess: r => {
      const failed = r.results.filter(x => x.status === "error")
      if (failed.length) toast.error(`수집 실패: ${failed.map(f => `${f.key}(${f.error ?? ""})`).join(", ")}`)
      else toast.success(`국면 이력 수집 완료 · ${formatNumber(r.results.reduce((a, x) => a + x.rows, 0))}행`)
    },
    onError: () => toast.error("국면 이력 수집 요청이 실패했습니다."),
  })
  return (
    <Section title="수동 수집">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm">국면 이력</span>
        <InfoTip label="국면 이력 수집 설명">S&P500·나스닥·버크셔 일별 시세, NBER 침체 월, 지금 시장 읽기 계열을 다시 받습니다 — 홈 › 매크로에서 씁니다.</InfoTip>
        <Button variant="outline" size="sm" className="ml-auto" onClick={run} disabled={collect.isPending}>
          {collect.isPending ? <><Spinner className="size-3.5" />받는 중…</> : "다시 받기"}
        </Button>
      </div>
    </Section>
  )
}
