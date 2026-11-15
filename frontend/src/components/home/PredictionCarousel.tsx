import { useRef } from "react"
import { PUBLIC_ACCESS } from "@/lib/accessMode"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { HomeBlock } from "@/components/home/HomeSection"
import { BlockError } from "@/components/home/blockState"
import { PinButton, PredictionDetailDialog, closeLabel, usePredictionDetailParam } from "@/components/home/PredictionDetailDialog"
import { AreaSpark } from "@/components/shared/Spark"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { usePredictions } from "@/hooks/usePredictions"
import { track } from "@/lib/usage"
import { cn } from "@/lib/utils"
import { formatKstSlashDate, formatNumber, formatPp, formatProbability } from "@/utils/format"
import type { KalshiEvent } from "@/types"

const CARD_W = 280
const CARD_H = 268

/**
 * 예측시장(Kalshi) — 홈 › 대시보드 '이번 주 바뀐 서사' 위. 금융·경제·테크·정치 인기 이벤트 + 추적 중인 이벤트(맨 앞)를 가로로 넘겨 본다.
 * 카드 = 카테고리 · 마감일 · 추적 핀 / 질문 / 대표 결과 60일 추이선 / 결과 3개(확률 막대·변화) / 거래량. 누르면 상세 창(`?pm=`).
 */
export function PredictionCarousel() {
  const q = usePredictions()
  const viewport = useRef<HTMLDivElement>(null)
  const scroll = (dir: 1 | -1) => {
    const el = viewport.current?.querySelector<HTMLElement>("[data-slot=scroll-area-viewport]")
    el?.scrollBy({ left: dir * (CARD_W + 12) * 2, behavior: "smooth" })
  }
  const items = q.data?.items ?? []
  return (
    <section aria-label="예측시장">
      <HomeBlock label="predictions" title="예측시장"
        info={PUBLIC_ACCESS ? <>Kalshi에서 저장한 금융·경제·테크·정치 이벤트입니다. 목록과 상세의 저장 시각은 다를 수 있으며 실시간 가격이 아닙니다. 확률은 저장 당시 최근 체결가, 변화는 이전 수집분 대비, 추이선은 보관된 일봉입니다. 기준선이 여러 개인 시장은 확률 50%에 가까운 기준선을 보입니다.</> : <>Kalshi에서 금융·경제·테크·정치 카테고리의 인기 이벤트를 하루 세 번(08:00·16:00·23:00) 받습니다. 금융·경제 칸을 더 많이 둡니다. 카드 오른쪽 위 핀으로 추적하면 인기순에서 빠져도 계속 받아 맨 앞에 둡니다. 확률은 최근 체결가, 변화는 약 하루 전 수집분 대비, 추이선은 대표 결과의 최근 60일입니다. 기준선이 여러 개인 시장('~ 이상')은 확률 50%에 가까운 기준선을 보입니다.</>}
        asOf={q.data?.fetched_at ? formatKstSlashDate(q.data.fetched_at) : null}
        actions={items.length > 0 && <div className="flex gap-1 max-sm:hidden">
          <Button variant="ghost" size="icon" className="size-7" aria-label="이전" onClick={() => scroll(-1)}><ChevronLeft className="size-4" /></Button>
          <Button variant="ghost" size="icon" className="size-7" aria-label="다음" onClick={() => scroll(1)}><ChevronRight className="size-4" /></Button>
        </div>}>
        {q.isPending ? <div className="flex gap-3 overflow-hidden">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="shrink-0" style={{ width: CARD_W, height: CARD_H }} />)}</div>
          : q.isError ? <BlockError message="예측시장을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
          : items.length === 0 ? <p className="py-6 text-sm text-muted-foreground">아직 받은 예측시장이 없어요.</p>
          : <div ref={viewport}>
            <ScrollArea className="w-full">
              <ul className="flex snap-x snap-mandatory gap-3 pb-3">
                {items.map(e => <li key={e.event_ticker} className="snap-start"><EventCard e={e} /></li>)}
              </ul>
              <ScrollBar orientation="horizontal" />
            </ScrollArea>
          </div>}
      </HomeBlock>
      <PredictionDetailDialog />
    </section>
  )
}

function EventCard({ e }: { e: KalshiEvent }) {
  const { show } = usePredictionDetailParam()
  const spark = (e.spark ?? []).map(p => p[1])
  return <div className={cn("relative flex shrink-0 flex-col gap-2 border bg-surface p-3", e.pinned && "border-ink/40")} style={{ width: CARD_W, height: CARD_H }}>
    {/* 카드 전체 = 상세 열기(투명 버튼을 내용 위에 덮는다 — 추이선 svg를 버튼 안에 넣으면 아이콘 크기 규칙에 줄어든다) */}
    <Button variant="ghost" aria-label={`${e.title} 자세히`}
      onClick={() => { track("action", "predictions.open", { entity: `kalshi:${e.event_ticker}` }); show(e.event_ticker) }}
      className="absolute inset-0 h-auto rounded-none p-0 hover:bg-chip/40 focus-visible:bg-chip/40" />
    <div className="flex items-center gap-2 text-[11.5px] text-ink-3">
      <Badge variant="outline" className="font-normal">{e.category_label}</Badge>
      {e.close_ts && <span className="font-mono tabular-nums">{closeLabel(e.close_ts)} 마감</span>}
      <PinButton eventTicker={e.event_ticker} seriesTicker={e.series_ticker} pinned={!!e.pinned} className="relative z-10 -my-1 -mr-1.5 ml-auto" />
    </div>
    <p className="line-clamp-2 min-h-[2.75em] shrink-0 text-[13.5px] leading-snug font-semibold" title={e.title}>{e.title}</p>
    <div className="h-9 shrink-0">{spark.length > 1 && <AreaSpark data={spark} height={36} label={`${e.outcomes[0]?.label ?? ""} 최근 ${spark.length}일 확률 추이`} />}</div>
    <ul className="mt-auto flex flex-col gap-1.5">
      {e.outcomes.map(o => <li key={o.label} className="flex flex-col gap-0.5">
        <div className="flex items-baseline gap-2 text-[12px]">
          <span className="min-w-0 flex-1 truncate text-ink-2" title={o.label}>{o.label}</span>
          {o.change != null && o.change !== 0 && <span className="font-mono text-[11px] text-ink-3 tabular-nums">{formatPp(o.change, 0)}</span>}
          <span className="w-9 text-right font-mono font-semibold tabular-nums">{formatProbability(o.price)}</span>
        </div>
        <div className="h-1 bg-chip" aria-hidden><div className="h-full bg-ink" style={{ width: `${Math.max(0, Math.min(100, o.price))}%` }} /></div>
      </li>)}
    </ul>
    {e.recent_volume != null && <span className="text-[11px] text-ink-3">최근 거래 {formatNumber(e.recent_volume)}계약</span>}
  </div>
}
