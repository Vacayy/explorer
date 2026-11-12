import { useRef } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { HomeBlock } from "@/components/home/HomeSection"
import { BlockError } from "@/components/home/blockState"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { usePredictions } from "@/hooks/usePredictions"
import { track } from "@/lib/usage"
import { formatKstSlashDate, formatNumber, formatPp, formatProbability } from "@/utils/format"
import type { KalshiEvent } from "@/types"

const CARD_W = 280

/**
 * 예측시장(Kalshi) — 홈 › 대시보드 '이번 주 바뀐 서사' 위. 금융·경제·테크·정치 인기 이벤트를 가로로 넘겨 본다(칸 안 가로 스크롤 + 좌우 버튼).
 * 카드 = 카테고리 · 마감일 / 질문 / 결과 3개(확률 막대·변화) / 거래량. 누르면 Kalshi 페이지(새 탭).
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
        info={<>Kalshi에서 금융·경제·테크·정치 카테고리의 인기 이벤트를 하루 세 번(08:00·16:00·23:00) 받습니다. 금융·경제 칸을 더 많이 둡니다. 확률은 최근 체결가이고, 변화는 약 하루 전 수집분 대비입니다. 기준선이 여러 개인 시장('~ 이상')은 확률 50%에 가까운 기준선을 보입니다.</>}
        asOf={q.data?.fetched_at ? formatKstSlashDate(q.data.fetched_at) : null}
        actions={items.length > 0 && <div className="flex gap-1 max-sm:hidden">
          <Button variant="ghost" size="icon" className="size-7" aria-label="이전" onClick={() => scroll(-1)}><ChevronLeft className="size-4" /></Button>
          <Button variant="ghost" size="icon" className="size-7" aria-label="다음" onClick={() => scroll(1)}><ChevronRight className="size-4" /></Button>
        </div>}>
        {q.isPending ? <div className="flex gap-3 overflow-hidden">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-[212px] shrink-0" style={{ width: CARD_W }} />)}</div>
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
    </section>
  )
}

/** 마감일 — 올해면 MM/DD, 아니면 YYYY/MM/DD */
const closeLabel = (ts: string) => {
  const md = formatKstSlashDate(ts, false)
  return ts.slice(0, 4) === String(new Date().getFullYear()) ? md : `${ts.slice(0, 4)}/${md}`
}

function EventCard({ e }: { e: KalshiEvent }) {
  return <a href={e.url} target="_blank" rel="noreferrer" style={{ width: CARD_W }}
    onClick={() => track("action", "predictions.open", { entity: `kalshi:${e.event_ticker}` })}
    className="flex h-[212px] shrink-0 flex-col gap-2 border bg-surface p-3 transition-colors hover:bg-chip/60 focus-visible:bg-chip/60">
    <div className="flex items-center gap-2 text-[11.5px] text-ink-3">
      <Badge variant="outline" className="font-normal">{e.category_label}</Badge>
      {e.close_ts && <span className="ml-auto font-mono tabular-nums">{closeLabel(e.close_ts)} 마감</span>}
    </div>
    <p className="line-clamp-2 min-h-[2.75em] shrink-0 text-[13.5px] leading-snug font-semibold" title={e.title}>{e.title}</p>
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
  </a>
}
