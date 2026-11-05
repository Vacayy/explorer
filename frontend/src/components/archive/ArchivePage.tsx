import { Archive, Settings } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { InfoTip } from "@/components/shared/InfoTip"
import { PageContainer } from "@/components/shared/PageContainer"
import { cn } from "@/lib/utils"
import { formatNumber, formatPercent, formatRatio } from "@/utils/format"

/**
 * /archive — 보관함 (ia-redesign §4.33 · 상단 바 설정 메뉴 › 보관함). 메인 메뉴에서 뺐지만 지우지 않은 화면.
 * 카드가 리다이렉트 목적지를 가리키게 되면 뺀다 — VS 비교는 Peer 성과 비교로(D-300), 산업군 지도는 지웠다(D-319).
 */
export default function ArchivePage() {
  return (
    <PageContainer width="reading" gap="sm">
      <p className="flex items-center gap-1 text-caption text-muted-foreground"><Settings aria-hidden="true" className="size-3.5" />설정 › 보관함</p>
      <h1 className="flex items-center gap-2 text-page font-semibold">
        <Archive aria-hidden="true" className="size-5 text-muted-foreground" />보관함
        <InfoTip label="보관함 설명">자주 쓰지 않아 메인 메뉴에서 뺀 화면입니다. 지운 것이 아니며 여기나 ⌘K로 열 수 있습니다.</InfoTip>
      </h1>
      {/* 신호 성적표 — 탐색 해체로 이관 (D-057). 자주 안 보는 자기검증 도구 */}
      <BacktestSection />
    </PageContainer>
  )
}

interface Backtest {
  items: { date: string; name: string; stock_code: string | null; ret_5d: number | null }[]
  avg_ret: number | null
  hit_rate: number | null
  n: number
}

/** 신호 성적표 — 언급 급증 후 5거래일 수익률. 로딩은 이 블록만 스켈레톤, 실패·0건이면 블록을 숨긴다 */
function BacktestSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["spine", "backtest"],
    queryFn: async () => (await api.get("/api/spine/signals/backtest")).data as Backtest,
    staleTime: 30 * 60_000,
  })
  if (isLoading) return <Skeleton className="h-28 w-full" />
  if (!data || data.n === 0) return null
  const done = data.items.filter((i) => i.ret_5d != null).slice(0, 12)
  return (
    <Card className="gap-0 py-0" aria-label="신호 성적표" data-backtest>
      <header className="flex flex-wrap items-baseline gap-x-3 px-4 pt-4">
        <h2 className="text-section font-semibold">신호 성적표 — 언급 급증 후 5거래일</h2>
        <span className="font-mono text-xs tabular-nums">
          평균 <b className={cn(data.avg_ret != null && (data.avg_ret > 0 ? "text-up" : data.avg_ret < 0 ? "text-down" : ""))}>{formatPercent(data.avg_ret)}</b>
          <span className="text-muted-foreground"> · 적중 {formatRatio(data.hit_rate)} · {formatNumber(data.n)}건</span>
        </span>
      </header>
      <div className="space-y-2 px-4 py-3">
        {done.length === 0
          ? <p className="bg-muted/60 px-3 py-2 text-sm" data-backtest-pending>최근 신호 {data.items.length}건은 아직 5거래일이 지나지 않았습니다.</p>
          : <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
            {done.map((i, idx) => (
              <span key={idx}>
                <span className="text-muted-foreground">{i.date.slice(5)}</span> {i.name}{" "}
                <b className={i.ret_5d! > 0 ? "text-up" : i.ret_5d! < 0 ? "text-down" : ""}>{formatPercent(i.ret_5d)}</b>
              </span>
            ))}
          </div>}
        <p className="flex items-center gap-1 text-caption text-muted-foreground">
          과거 신호의 사후 수익률
          <InfoTip label="성적표 설명">신호의 유효성 자체를 검증하기 위한 것입니다. 투자 추천이 아닙니다.</InfoTip>
        </p>
      </div>
    </Card>
  )
}
