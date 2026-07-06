import { formatRelativeTime } from "@/utils/format"

/** 데이터 신선도 표시 (data-freshness 정책) — 섹션 헤더 우측에 부착 */
export function FreshnessStamp({ asOf }: { asOf: string }) {
  return (
    <span className="text-[11px] text-muted-foreground tabular-nums">
      {formatRelativeTime(asOf)} 기준
    </span>
  )
}
