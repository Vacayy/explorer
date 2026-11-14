import type { z } from "zod"
import { collectPlanSchema } from "@/api/contracts"
// 컨콜 수집 직접 트리거 (D-121) — 버튼 + 진행 상태 + 마지막 실행 결과.
// 1회 ~20분(AV 무료 한도 5/min)이라 서버가 백그라운드로 돌리고 여기선 상태를 폴링한다.
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Download, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import api from "@/api/client"
import { apiQuery, toApiError } from "@/api/query"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { formatRelativeTime } from "@/utils/format"

export interface CollectStatus {
  running: boolean
  started_at: string | null
  budget: number | null
  enabled: boolean
  last_run: { status: string; summary: string; duration_ms: number | null; ran_at: string } | null
}

type DryRun = z.infer<typeof collectPlanSchema>

const BUDGET = 22   // AV 무료 한도 25/day — 여유 3건은 캘린더·재시도용

function when(ts: string | null): string {
  if (!ts) return "-"
  return formatRelativeTime(ts.includes("T") ? ts : ts.replace(" ", "T") + "Z")
}

export default function CollectTranscripts() {
  const qc = useQueryClient()
  const [plan, setPlan] = useState<DryRun | null>(null)

  const { data: status } = useQuery({
    ...apiQuery<CollectStatus>({
      key: ["spine", "transcript", "collect", "status"],
      url: "/api/spine/transcript/collect/status",
      staleTime: 0,
    }),
    // 진행 중일 때만 자주 확인 — 20분짜리 작업이라 끝나면 폴링을 멈춘다
    refetchInterval: (q) => (q.state.data?.running ? 15_000 : false),
  })

  const preview = useMutation({
    mutationFn: () =>
      api.post("/api/spine/transcript/collect?dry_run=1").then((r) => r.data as DryRun),
    onSuccess: (d) => setPlan(d),
    onError: (e) => toast.error(toApiError(e).message),
  })

  const start = useMutation({
    mutationFn: () => api.post(`/api/spine/transcript/collect?budget=${BUDGET}`).then((r) => r.data),
    onSuccess: () => {
      toast.success("수집을 시작했습니다 — 완료까지 20분 내외")
      qc.invalidateQueries({ queryKey: ["spine", "transcript", "collect", "status"] })
    },
    onError: (e) => toast.error(toApiError(e).message),
  })

  const running = !!status?.running
  const last = status?.last_run

  return (
    <Card>
      <CardContent className="space-y-2 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Download className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="text-[13px] font-semibold">컨콜 수집</span>
          <span className="text-[11px] text-muted-foreground">
            Alpha Vantage 무료 한도 하루 {BUDGET + 3}건 · 1회 실행 20분 내외
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => preview.mutate()}
              disabled={preview.isPending || running}
            >
              {preview.isPending ? <Spinner className="h-3.5 w-3.5" /> : "요청 계획 보기"}
            </Button>
            <Button size="sm" onClick={() => start.mutate()} disabled={running || start.isPending}>
              {running ? (
                <><Spinner className="mr-1.5 h-3.5 w-3.5" /> 수집 중…</>
              ) : (
                <><RefreshCw className="mr-1.5 h-3.5 w-3.5" /> 지금 수집</>
              )}
            </Button>
          </div>
        </div>

        {status && !status.enabled && (
          <p className="flex items-center gap-1 text-[11px] text-hypothesis">
            <AlertTriangle className="h-3 w-3" /> 관리자 페이지에서 '컨콜 수집' 작업이 off 상태입니다 — 켜야 실행됩니다.
          </p>
        )}

        {running && (
          <p className="text-[11px] text-muted-foreground">
            {when(status?.started_at ?? null)} 시작 · 예산 {status?.budget}건 · 완료 후 목록에 반영됩니다
          </p>
        )}

        {plan && !running && (
          <p className="text-[11px] text-muted-foreground">
            요청 대기 {plan.would_request}건 중 이번 회차 {Math.min(plan.would_request, plan.budget)}건
            {plan.over_budget > 0 && ` · 예산 초과 ${plan.over_budget}건은 다음 회차`}
            {plan.planned.length > 0 && ` · 우선순위: ${plan.planned.slice(0, 5).join(", ")}`}
          </p>
        )}

        {last && (
          <p className="text-[11px] text-muted-foreground">
            마지막 실행 {when(last.ran_at)}
            {last.status !== "ok" && <span className="text-hypothesis"> ({last.status})</span>}
            {/* 요약이 수집기의 원본 dict 문자열이면 숫자만 사람 말로 */}
            {last.summary && ` · ${readableSummary(last.summary)}`}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

/** "{'requests': 0, 'stored': 3, ...}" 같은 수집기 요약을 '요청 0 · 저장 3'으로. 일반 문장은 그대로 */
const SUMMARY_LABEL: Record<string, string> = { requests: "요청", stored: "저장", empty: "빈 응답", budget: "남은 한도", skipped_cache: "캐시로 건너뜀", digested: "핵심 정리", proxies: "프록시" }
function readableSummary(s: string): string {
  if (!s.trim().startsWith("{")) return s
  const seen = new Map<string, string>()   // 안쪽 묶음(fool 등)의 같은 키는 처음 것만
  for (const m of s.matchAll(/'([a-z_]+)':\s*(-?\d+)/g)) if (SUMMARY_LABEL[m[1]] && !seen.has(m[1])) seen.set(m[1], m[2])
  return seen.size ? [...seen].map(([k, v]) => `${SUMMARY_LABEL[k]} ${v}`).join(" · ") : "완료"
}
