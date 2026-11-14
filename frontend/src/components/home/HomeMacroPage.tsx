import { useEffect } from "react"
import { useLocation, useSearchParams } from "react-router-dom"
import { BlockError, tone } from "@/components/home/blockState"
import { MacroLiquidity } from "@/components/home/MacroLiquidity"
import { RiskTiles } from "@/components/home/RiskTiles"
import { BrkPanel } from "@/components/regimes/BrkPanel"
import { BearTable, HistoryCompact, MapCard, OverlayCard, useHistoryParams } from "@/components/regimes/History"
import { NowPanel } from "@/components/regimes/NowPanel"
import { InfoTip } from "@/components/regimes/Section"
import { PageLayout } from "@/components/shared/PageLayout"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsMobile } from "@/hooks/use-mobile"
import { useAutoCollectRegimes, useEraState, usePricing, useRegimes } from "@/hooks/useRegimes"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { RegimesResponse } from "@/types"

const ANCHORS: [string, string][] = [
  ["#now-state", "1 추세 이탈"], ["#now-meaning", "2 금리의 뜻"], ["#now-temp", "3 온도"], ["#now-premises", "4 구루 전제"], ["#now-pricing", "5 시장 프라이싱"],
  ["#macro", "매크로·유동성"], ["#risk", "리스크 지표"], ["#history", "국면 이력"], ["#brk", "버크셔 vs 지수"],
]

/**
 * 홈 › 매크로 (시안 Home-Macro·Mobile-Macro·States-Macro, ia-redesign §4.16·§4.28) — 시장 전체의 숲.
 * 상태 줄 → 지금 시장은 5칸 → AI 해설 → 1~3·5·4 → 매크로·유동성 신호등 → 리스크 지표 → 국면 이력(지도·겹쳐 보기·버크셔·약세장 표).
 * 블록마다 따로 불러오고 따로 실패한다. 화면 전체 오류는 regimes·state·pricing 셋 다 실패했을 때만.
 * 모바일은 요약 화면이고 `?macro_view=full`이면 데스크톱과 같은 전체 섹션을 보인다.
 */
export default function HomeMacroPage() {
  const mobile = useIsMobile()
  const [params] = useSearchParams()
  const compact = mobile && params.get("macro_view") !== "full"
  const regimes = useRegimes()
  const era = useEraState()
  const pricing = usePricing(8)
  const auto = useAutoCollectRegimes(regimes)
  useHashScroll(!regimes.isPending && !era.isPending)

  // 시안 Home-Macro: 하위 메뉴 칩이 제목을 대신한다 — 제목은 화면 읽기용으로만
  const header = <h1 className="sr-only">매크로</h1>
  if (regimes.isError && era.isError && pricing.isError) return <PageLayout mode="document">
    {header}
    <BlockError message="매크로 화면 데이터를 하나도 불러오지 못했습니다" error={regimes.error}
      onRetry={() => { void regimes.refetch(); void era.refetch(); void pricing.refetch() }} />
  </PageLayout>

  return <PageLayout mode="document">
    {header}
    <div className="@container/market flex flex-col gap-4">
      <div className="space-y-3">
        <StatusLine data={regimes.data} pending={regimes.isPending} compact={compact} />
        {!compact && <nav aria-label="이 페이지에서" className="flex flex-wrap gap-1.5">
          {ANCHORS.map(([href, label]) => <a key={href} href={href} className="rounded-full border px-3 py-1 text-caption text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">{label}</a>)}
        </nav>}
      </div>
      <NowPanel regimes={regimes.data} compact={compact} />
      <MacroLiquidity compact={compact} />
      <RiskTiles compact={compact} />
      <section id="history" aria-labelledby="history-title" className="scroll-mt-24 space-y-3" data-macro-block="history">
        {!compact && <h2 id="history-title" className="pt-2 text-base font-semibold">국면 이력</h2>}
        {compact && <h2 id="history-title" className="sr-only">국면 이력</h2>}
        <History q={regimes} auto={auto} compact={compact} />
      </section>
    </div>
  </PageLayout>
}

/** 해시(#history 등)로 들어오면 데이터가 그려진 뒤 그 섹션으로 — 리다이렉트 /regimes → #history도 여기서 */
function useHashScroll(ready: boolean) {
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash || !ready) return
    const id = decodeURIComponent(hash.slice(1))
    const t = window.setTimeout(() => document.getElementById(id)?.scrollIntoView({ block: "start" }), 50)
    return () => window.clearTimeout(t)
  }, [hash, ready])
}

function StatusLine({ data, pending, compact }: { data?: RegimesResponse; pending: boolean; compact: boolean }) {
  if (pending) return <Skeleton className="h-5 w-full max-w-xl" />
  const cur = data?.current
  if (!cur) return null
  return <div className="flex items-start gap-2">
    <p id="now-status" className="min-w-0 flex-1 text-sm">
      S&P500은 <b className={cn(cur.kind === "bear" && "text-down-ink")}>{cur.kind === "bear" ? "약세장" : "강세장"}</b>(잠정, {cur.start}~)
      {" "}· 고점 대비 <span className={cn("font-mono tabular-nums", tone(cur.from_peak_pct))}>{formatPercent(cur.from_peak_pct)}</span>
      {!compact && <> · 저점 대비 <span className={cn("font-mono tabular-nums", tone(cur.from_trough_pct))}>{formatPercent(cur.from_trough_pct)}</span></>}
      {cur.trend && <> · 10개월선 {cur.trend === "up" ? "위" : "아래"}</>}
      {data?.as_of && <span className="text-muted-foreground"> · {data.as_of}{compact ? "" : " 종가"}</span>}
    </p>
    <InfoTip label="상태 줄 설명">S&P500 일별 종가에 대칭 20/20 규칙(Lunde–Timmermann)을 적용한 국면입니다. 마지막 전환 이후는 잠정이고, 10개월선은 월말 종가 기준 실시간 추세입니다.</InfoTip>
  </div>
}

function History({ q, auto, compact }: { q: ReturnType<typeof useRegimes>; auto: ReturnType<typeof useAutoCollectRegimes>; compact: boolean }) {
  const hp = useHistoryParams()
  if (q.isPending) return <div className="space-y-3"><Skeleton className="h-[460px] w-full rounded-card" /><Skeleton className="h-[320px] w-full rounded-card" /></div>
  if (q.isError) return <BlockError message="국면 이력을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
  const d = q.data
  if (!d.phases.length) {
    if (auto.failed) {
      const failed = auto.result?.results.filter(r => r.status === "error").map(r => r.key).join(", ")
      return <BlockError message={`지수 이력을 받지 못했습니다${failed ? ` (${failed})` : ""} · 관리자 화면에서 다시 받을 수 있습니다`} error={auto.error ?? undefined} onRetry={() => void q.refetch()} />
    }
    return <div role="status" aria-busy="true" className="space-y-3 border p-4" data-regimes-collecting>
      <p className="text-sm">처음 한 번 지수 이력을 받는 중입니다. S&P500(1927~) · 나스닥 · 버크셔 일별 시세와 NBER 침체 월이라 수십 초 걸립니다.</p>
      <Skeleton className="h-40 w-full" />
    </div>
  }
  if (compact) return <HistoryCompact data={d} />
  return <div className="flex flex-col gap-4">
    <MapCard data={d} range={hp.range} onRange={hp.setRange} />
    <OverlayCard data={d} range={hp.range} overlay={hp.overlay} onOverlay={hp.setOverlay} />
    <div id="brk" className="scroll-mt-24"><BrkPanel /></div>
    <BearTable data={d} />
  </div>
}
