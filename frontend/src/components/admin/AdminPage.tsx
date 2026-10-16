import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { PageContainer } from "@/components/shared/PageContainer"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ErrorState } from "@/components/shared/ErrorState"
import { cn } from "@/lib/utils"

/**
 * /admin — 운영 관리자 (D-055). cron 생성 작업 on/off + 최근 실행 로그.
 * 자동화가 늘수록 비용·가시성 통제판. 기계는 제안·사람은 통제(D-020 연장).
 */
interface JobStatus {
  name: string; label: string; description: string; entrypoint: string; enabled: boolean
  last_run: { status: string; summary: string | null; duration_ms: number | null; ran_at: string } | null
}
/** 데이터 신선도 (D-222) — 작업 종료 코드가 아니라 결과 데이터의 최신 시점 */
interface HealthItem {
  key: string; label: string; kind: string; owner: string; critical: boolean
  latest: string | null; expected: string | null; status: string; detail: string
}
interface JobRun { job: string; status: string; summary: string | null; duration_ms: number | null; ran_at: string }

const STATUS_CLS: Record<string, string> = {
  ok: "text-up border-up/40", skipped: "text-muted-foreground", error: "text-down border-down/50",
}

export default function AdminPage() {
  const qc = useQueryClient()
  const { data: jobs = [], isLoading } = useQuery(
    apiQuery<JobStatus[]>({ key: ["spine", "admin", "jobs"], url: "/api/spine/admin/jobs", staleTime: STALE.short }),
  )
  const { data: runs = [] } = useQuery(
    apiQuery<JobRun[]>({ key: ["spine", "admin", "runs"], url: "/api/spine/admin/runs?limit=40", staleTime: STALE.short }),
  )
  const health = useQuery(
    apiQuery<HealthItem[]>({ key: ["spine", "admin", "health"], url: "/api/spine/admin/health", staleTime: STALE.short }),
  )
  const stale = (health.data ?? []).filter((h) => h.status !== "ok")
  const toggle = useMutation({
    mutationFn: async (b: { name: string; enabled: boolean }) =>
      (await api.post("/api/spine/admin/flag", b)).data,
    onSuccess: (_d, b) => {
      toast.success(`${b.name} ${b.enabled ? "켬" : "끔"}`)
      qc.invalidateQueries({ queryKey: ["spine", "admin", "jobs"] })
    },
    onError: () => toast.error("변경 실패"),
  })

  return (
    <PageContainer gap="sm">
      <div>
        <h2 className="text-xl font-bold">관리자</h2>
        <p className="text-sm text-muted-foreground">자동 생성 작업 on/off · 최근 실행 내역 — 비용·가시성 통제</p>
      </div>

      {/* 데이터 신선도 */}
      <section aria-label="데이터 신선도" className="space-y-1.5">
        <div className="flex items-baseline gap-2">
          <h3 className="text-sm font-medium">데이터 신선도</h3>
          {health.data && (
            <span className={cn("text-caption", stale.length ? "text-down" : "text-muted-foreground")}>
              {stale.length ? `지연 ${stale.length}건` : "모두 최신"}
            </span>
          )}
        </div>
        <p className="text-caption text-muted-foreground">작업이 정상 종료돼도 결과가 비거나 묵을 수 있어, 저장된 데이터의 최신 시점을 기대치와 비교합니다. ‘경고’ 항목은 홈 브리핑·텔레그램에도 표시됩니다.</p>
        {health.isPending && <Skeleton className="h-48 w-full rounded-xl" />}
        {health.isError && <ErrorState message="신선도 점검을 불러오지 못했습니다." onRetry={() => health.refetch()} />}
        {health.data && (
          <div className="rounded-lg border">
            <Table>
              <TableHeader><TableRow>
                <TableHead>데이터</TableHead><TableHead>상태</TableHead><TableHead>최신</TableHead>
                <TableHead>기대</TableHead><TableHead className="hidden md:table-cell">채우는 곳</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {health.data.map((h) => (
                  <TableRow key={h.key}>
                    <TableCell className="text-sm">{h.label}{h.critical && <Badge variant="outline" className="ml-1.5 text-[9px]">경고</Badge>}</TableCell>
                    <TableCell className="text-[11px]">
                      <Badge variant="outline" className={cn("text-[9px]", h.status === "ok" ? STATUS_CLS.ok : STATUS_CLS.error)}>{h.status === "ok" ? "최신" : h.status === "stale" ? "지연" : "오류"}</Badge>
                      {h.detail && <span className="ml-1.5 text-muted-foreground">{h.detail}</span>}
                    </TableCell>
                    <TableCell className="text-[11px] tabular-nums text-muted-foreground">{h.latest ? h.latest.slice(0, 16) : "-"}</TableCell>
                    <TableCell className="text-[11px] tabular-nums text-muted-foreground">{h.expected ?? "-"}</TableCell>
                    <TableCell className="hidden text-[11px] text-muted-foreground md:table-cell">{h.owner}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      {/* 작업 on/off */}
      <div className="space-y-2">
        {isLoading && <Skeleton className="h-40 w-full rounded-xl" />}
        {jobs.map((j) => (
          <Card key={j.name}>
            <CardContent className="py-3 flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{j.label}</span>
                  <code className="text-[10px] font-mono text-muted-foreground bg-muted px-1 py-0.5 rounded">{j.name}</code>
                  {j.last_run && (
                    <Badge variant="outline" className={cn("text-[9px]", STATUS_CLS[j.last_run.status] ?? "")}>
                      {j.last_run.status}
                    </Badge>
                  )}
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5">
                  <code className="font-mono text-muted-foreground/90">{j.entrypoint}</code> · {j.description}
                </div>
                {j.last_run && (
                  <div className="text-[10px] text-muted-foreground/80 mt-0.5 tabular-nums">
                    최근 {j.last_run.ran_at.slice(5, 16)}
                    {j.last_run.duration_ms != null ? ` · ${(j.last_run.duration_ms / 1000).toFixed(1)}s` : ""}
                    {j.last_run.summary ? ` · ${j.last_run.summary}` : ""}
                  </div>
                )}
              </div>
              <Switch checked={j.enabled} disabled={toggle.isPending}
                onCheckedChange={(v) => toggle.mutate({ name: j.name, enabled: v })} />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 최근 실행 내역 */}
      <div>
        <div className="text-sm font-medium mb-1.5">최근 실행 내역</div>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">아직 기록된 실행이 없습니다 — cron이 돌면 쌓입니다.</p>
        ) : (
          <div className="rounded-lg border divide-y">
            {runs.map((r, i) => (
              <div key={i} className="flex items-center gap-2 px-3 py-1.5 text-[11px]">
                <span className="text-muted-foreground tabular-nums shrink-0">{r.ran_at.slice(5, 16)}</span>
                <Badge variant="outline" className={cn("text-[9px] shrink-0", STATUS_CLS[r.status] ?? "")}>{r.status}</Badge>
                <span className="font-medium shrink-0">{r.job}</span>
                <span className="text-muted-foreground truncate min-w-0 flex-1">{r.summary}</span>
                {r.duration_ms != null && <span className="text-muted-foreground/70 tabular-nums shrink-0">{(r.duration_ms / 1000).toFixed(1)}s</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </PageContainer>
  )
}
