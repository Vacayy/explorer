import { Fragment } from "react"
import { Loader2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Markdown } from "@/components/shared/Markdown"
import { stockLensQuery, stockLensComputeQuery } from "@/api/spine"
import { PageContainer } from "@/components/shared/PageContainer"
import { ProposalPanel } from "@/components/shared/ProposalPanel"
import { ErrorState } from "@/components/shared/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import type { LensReading, Quadrant } from "@/types"

// 가치 = 미래 이익·현금흐름 극대화 확신의 강도 / 추세 = 시장이 이미 반영한 위치
const VALUE_STANCE: Record<string, { label: string; cls: string }> = {
  강: { label: "확신 강", cls: "text-up border-up/40" },
  중: { label: "확신 중", cls: "text-hypothesis border-hypothesis/40" },
  약: { label: "확신 약", cls: "text-down border-down/40" },
}
const TREND_STANCE: Record<string, { label: string; cls: string }> = {
  초입: { label: "초입·소외", cls: "text-up border-up/40" },
  진행: { label: "추세 진행", cls: "text-up border-up/40" },
  성숙: { label: "성숙·과열", cls: "text-down border-down/40" },
  훼손: { label: "추세 훼손", cls: "text-down border-down/40" },
  불명확: { label: "위치 불명확", cls: "text-muted-foreground border-border" },
}

/**
 * 투자 렌즈 탭 — 원칙 원장(가치/추세)에 비춰 이 종목을 읽는다 (docs/specs/investor-lens.md).
 * 판정 오라클이 아니라 프레임(hypothesis). 두 렌즈가 갈리는 지점이 신호(4상한 미니뷰).
 * 게으른 생성: 원칙·재료(질적 추세 상태)가 바뀌면 stale → 자동 재생성.
 */
export default function LensPage({ stockCode }: { stockCode: string; corpCode?: string }) {
  const bundle = useQuery(stockLensQuery(stockCode))
  const vStale = bundle.data?.value?.stale ?? false
  const tStale = bundle.data?.trend?.stale ?? false
  const vCompute = useQuery(stockLensComputeQuery(stockCode, "value", !!bundle.data?.value && vStale))
  const tCompute = useQuery(stockLensComputeQuery(stockCode, "trend", !!bundle.data?.trend && tStale))

  if (bundle.isLoading) return <LensSkeleton />
  if (bundle.isError)
    return (
      <PageContainer>
        <ErrorState onRetry={() => bundle.refetch()} />
      </PageContainer>
    )

  const value = vCompute.data ?? bundle.data?.value ?? null
  const trend = tCompute.data ?? bundle.data?.trend ?? null
  const quadrant = bundle.data?.quadrant ?? null
  const hasValue = bundle.data?.value != null
  const hasTrend = bundle.data?.trend != null

  return (
    <PageContainer gap="sm">
      <p className="text-xs text-muted-foreground">
        투자 원칙 원장에 비춰 이 종목을 읽습니다 — 판정이 아니라 관점입니다. 두 렌즈가 갈리는 지점이 곧 신호이며,
        원칙 원장(<code>vault/principles</code>)을 수정하면 다음 열람 때 자동으로 다시 읽습니다.
      </p>

      {quadrant && <QuadrantMini q={quadrant} />}

      {hasValue ? (
        <LensCard kind="value" label="가치 렌즈 · 성장주도 펀더멘탈" reading={value} loading={vCompute.isFetching} />
      ) : (
        <ProposalPanel title="가치 렌즈 · 성장주도 펀더멘탈" contentClassName="text-xs text-muted-foreground">
          재료가 부족합니다(재무·컨센서스 없음) — 판독을 유보합니다.
        </ProposalPanel>
      )}

      {hasTrend ? (
        <LensCard kind="trend" label="추세 렌즈 · 추세추종" reading={trend} loading={tCompute.isFetching} />
      ) : (
        <ProposalPanel title="추세 렌즈 · 추세추종" contentClassName="text-xs text-muted-foreground">
          가격 데이터가 부족합니다 — 판독을 유보합니다.
        </ProposalPanel>
      )}
    </PageContainer>
  )
}

// 4상한 — 가치 확신(강·중 / 약) × 추세 위치(초입·진행 / 성숙·훼손). 현재 셀 강조.
function QuadrantMini({ q }: { q: Quadrant }) {
  const rows = [
    ["기회", "늦은 진입"],
    ["회피", "과열 경고"],
  ]
  return (
    <div className="rounded-xl border p-3 space-y-2">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-semibold">{q.cell}</span>
        <span className="text-[11px] text-muted-foreground">
          가치 {q.value_axis} · 추세 {q.trend_axis}
        </span>
      </div>
      <div className="grid grid-cols-[auto_1fr_1fr] gap-1 text-[10px]">
        <div />
        <div className="text-center text-muted-foreground pb-1">추세 초입·진행</div>
        <div className="text-center text-muted-foreground pb-1">추세 성숙·훼손</div>
        {rows.map((row, ri) => (
          <Fragment key={ri}>
            <div className="flex items-center pr-2 text-muted-foreground">{ri === 0 ? "확신 강·중" : "확신 약"}</div>
            {row.map((c) => (
              <div
                key={c}
                className={`rounded-md px-2 py-2 text-center border ${
                  c === q.cell
                    ? "border-hypothesis bg-hypothesis/10 font-semibold text-hypothesis"
                    : "border-border/40 text-muted-foreground"
                }`}
              >
                {c}
              </div>
            ))}
          </Fragment>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">{q.note}</p>
    </div>
  )
}

function LensCard({
  kind,
  label,
  reading,
  loading,
}: {
  kind: "value" | "trend"
  label: string
  reading: LensReading | null
  loading: boolean
}) {
  const map = kind === "value" ? VALUE_STANCE : TREND_STANCE
  const stance = reading?.stance ? map[reading.stance] : null
  const prefix = kind === "value" ? "미래 확신 " : "위치 · "
  return (
    <ProposalPanel
      title={label}
      subtitle={reading?.created_at ? `${reading.created_at.slice(0, 16).replace("T", " ")} 기준` : undefined}
      maxHeight="70vh"
      className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]"
      contentClassName="space-y-3"
    >
      {loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          원칙에 비춰 이 종목을 읽는 중… (수십 초 걸릴 수 있습니다)
        </div>
      )}
      {stance && (
        <Badge variant="outline" className={`text-[11px] ${stance.cls}`}>
          {prefix}
          {stance.label}
        </Badge>
      )}
      {reading?.body && <Markdown className={loading ? "opacity-60" : ""}>{reading.body}</Markdown>}
      {reading?.signals && reading.signals.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 border-t pt-2">
          <span className="text-[10px] text-muted-foreground shrink-0">근거</span>
          {reading.signals.map((s) => (
            <Badge key={s} variant="secondary" className="text-[10px] font-normal">
              {s}
            </Badge>
          ))}
        </div>
      )}
      {reading?.body && (
        <div className="text-right">
          <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
            AI 관점 · 원칙 원장 기반 — 판정 아님, 검증 필요
          </Badge>
        </div>
      )}
      {!reading?.body && !loading && (
        <p className="text-xs text-muted-foreground py-1">
          {reading?.status === "unavailable"
            ? "LLM 엔진이 연결되면 열람 시 자동 생성됩니다."
            : "곧 자동으로 생성됩니다. 잠시만 기다려 주세요."}
        </p>
      )}
    </ProposalPanel>
  )
}

function LensSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-64 w-full rounded-xl" />
    </div>
  )
}
