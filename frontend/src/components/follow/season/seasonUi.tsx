// 실적 시즌 화면 공용 조각 — 형식 원칙: 섹션 하나에 카드 하나, 안은 소제목(h3)+불릿, 숫자는 문장 안에 (docs/specs/earnings-season.md §화면)
import type { ReactNode } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatPp } from "@/utils/format"
import { cn } from "@/lib/utils"
import type { CoreReason, EvalVerdict } from "@/types"

/** 섹션 = 카드 하나. title은 h2, note는 제목 옆 작은 설명 */
export function Section({ title, note, children, className }: { title?: ReactNode; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={cn("min-w-0", className)}>
      <CardContent className="flex flex-col gap-2">
        {title && (
          <h2 className="flex flex-wrap items-baseline gap-2 text-[15px] font-semibold">
            {title}{note && <span className="text-caption font-normal text-muted-foreground">{note}</span>}
          </h2>
        )}
        {children}
      </CardContent>
    </Card>
  )
}

/** 짧은 섹션 둘을 데스크톱에서 나란히 */
export function Cols({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 md:grid-cols-2">{children}</div>
}

export function H3({ children, className }: { children: ReactNode; className?: string }) {
  return <h3 className={cn("mt-2 flex flex-wrap items-baseline gap-2 text-sm font-semibold first:mt-0", className)}>{children}</h3>
}

/** 불릿 목록 — lead면 첫 줄 굵게(핵심 한 문장) */
export function Bullets({ items, lead = false }: { items: ReactNode[]; lead?: boolean }) {
  return (
    <ul className="flex list-disc flex-col gap-1 pl-5 text-sm marker:text-muted-foreground">
      {items.map((x, i) => <li key={i} className={cn(lead && i === 0 && "font-semibold")}>{x}</li>)}
    </ul>
  )
}

export const Meta = ({ children, className }: { children: ReactNode; className?: string }) =>
  <p className={cn("text-caption text-muted-foreground", className)}>{children}</p>

/** 업종 ETF 대비 %p — 상승 빨강·하락 파랑(한국 컨벤션) */
export function Pp({ v, className }: { v: number | null | undefined; className?: string }) {
  return <span className={cn("tabular-nums", v == null ? "text-muted-foreground" : v > 0 ? "text-up" : v < 0 ? "text-down" : "", className)}>{formatPp(v, 1)}</span>
}

export const mmdd = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`
/** '2026Q3' → '2026 Q3' */
export const seasonLabel = (s: string) => `${s.slice(0, 4)} Q${s.slice(-1)}`

export const VERDICT: Record<EvalVerdict, string> = { hit: "맞힘", underweighted: "덜 봄", noise: "과하게 봄", missed: "못 봄", minor: "영향 작음" }
export const VERDICT_CLS: Record<EvalVerdict, string> = {
  hit: "bg-chart-green/10 text-chart-green", underweighted: "bg-hypothesis/10 text-hypothesis",
  noise: "bg-muted text-muted-foreground", missed: "bg-hypothesis/10 text-hypothesis", minor: "bg-muted text-muted-foreground",
}
export const WEIGHT: Record<"high" | "mid" | "low", string> = { high: "중요", mid: "보통", low: "낮음" }

/** 섹터 판정 태그 — 판정이 없으면 '숫자만' */
export function VerdictBadge({ verdict }: { verdict: string | null | undefined }) {
  return <Badge variant={verdict ? "secondary" : "outline"} className={cn("font-normal", !verdict && "text-muted-foreground")}>{verdict ?? "숫자만"}</Badge>
}

/** 핵심 이유의 짧은 태그 — 전체 기준 문장은 season.core.criteria */
export const SHORT_REASON: Record<CoreReason, string> = { cap: "시총", mention: "언급", holding_chain: "보유 체인", dc_chain: "DC 체인", pinned: "고정" }

export const CoreBadge = ({ core }: { core: CoreReason[] | undefined }) =>
  core?.length ? <Badge variant="outline" className="border-primary/40 font-normal text-primary">핵심</Badge> : null

/** 발표 전 기대 준비 상태 — qualitative는 정성 정리(쟁점·기준)까지 있는지 */
export function expectationStatus(e: { d7: boolean; d1: boolean; qualitative: boolean } | null | undefined) {
  if (!e) return "기대 정리 전"
  if (e.qualitative) return e.d1 ? "전날 기대 정리됨" : "일주일 전 기대 정리됨"
  return e.d1 || e.d7 ? "숫자만" : "기대 정리 전"
}

/** 시즌 화면 URL 쿼리 하나를 바꾼다(나머지 유지, 기록 대신 교체) — URL이 유일한 상태 소스 */
export function patchParams(p: URLSearchParams, patch: Record<string, string | null>) {
  const n = new URLSearchParams(p)
  for (const [k, v] of Object.entries(patch)) { if (v == null) n.delete(k); else n.set(k, v) }
  return n
}
