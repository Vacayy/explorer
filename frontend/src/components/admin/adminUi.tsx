import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { useSetFlag } from "@/hooks/useAdmin"
import { cn } from "@/lib/utils"

/** 작업 실행 상태(job_runs.status) — 한국어 배지 */
const RUN_STATUS: Record<string, { label: string; cls: string }> = {
  ok: { label: "정상", cls: "text-fact border-fact/40" },
  skipped: { label: "건너뜀", cls: "text-muted-foreground" },
  partial: { label: "부분", cls: "text-chart-warning border-chart-warning/50" },
  error: { label: "실패", cls: "text-destructive border-destructive/50" },
}

export function RunStatusBadge({ status, className }: { status: string | null; className?: string }) {
  const s = status ? RUN_STATUS[status] : null
  return (
    <Badge variant="outline" className={cn("shrink-0 text-[10px]", s?.cls ?? "text-muted-foreground", className)}>
      {s?.label ?? (status ?? "기록 없음")}
    </Badge>
  )
}

/** 데이터 신선도 상태(ok·stale·error) */
export function FreshnessBadge({ status }: { status: string }) {
  const [label, cls] = status === "ok" ? ["최신", "text-fact border-fact/40"]
    : status === "stale" ? ["지연", "text-chart-warning border-chart-warning/50"] : ["오류", "text-destructive border-destructive/50"]
  return <Badge variant="outline" className={cn("shrink-0 text-[10px]", cls)}>{label}</Badge>
}

/**
 * 자동 정리 '적용' 스위치(auto_curation_apply, D-295) — 작업·신선도와 자동 정리 두 보기가 같이 쓴다.
 * 켜면 다음 판정부터 별칭·노드 병합·지식 승격이 실제로 바뀌므로 확인 창을 거친다. 끄기는 바로.
 */
export function CurationApplySwitch({ enabled, disabled }: { enabled: boolean; disabled?: boolean }) {
  const flag = useSetFlag()
  const [confirm, setConfirm] = useState(false)
  return (
    <>
      <Switch aria-label="자동 정리 적용" checked={enabled} disabled={disabled || flag.isPending}
        onCheckedChange={v => v ? setConfirm(true) : flag.mutate({ name: "auto_curation_apply", enabled: false })} />
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>자동 정리를 적용할까요?</AlertDialogTitle>
            <AlertDialogDescription>
              다음 주간 제안 스캔부터 판정대로 별칭·노드 병합·지식 승격을 실제로 처리하고, 정리 작업은 인박스에서 빠집니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>취소</AlertDialogCancel>
            <AlertDialogAction onClick={() => flag.mutate({ name: "auto_curation_apply", enabled: true })}>적용 켜기</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

/** 판정 시각 다음 회차 — 주간 제안 스캔(launchd proposals, 일 07:20 KST · scripts/install_launchd.py) 끝에 돈다 */
export const NEXT_CURATION_LABEL = "다음 일 07:20"
