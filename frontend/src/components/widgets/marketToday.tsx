/* ── Market Today — 오늘 장중 실시간 소스 화두 (docs/specs/market-today.md) ── */
import { useState } from "react"
import { Link } from "react-router-dom"
import { Sparkles } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { NarrativeChipLine } from "@/components/world/NarrativeChipLine"
import { useMarketToday } from "@/hooks/useMarketToday"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { TodayTopic } from "@/types"
import type { WidgetBodyProps, WidgetMeta } from "./types"

/** 한국 관례: 상승 빨강·하락 파랑 */
const tone = (v: number | null | undefined) => v == null || v === 0 ? "" : v > 0 ? "text-up" : "text-down"

export function useMarketTodayMeta(): WidgetMeta {
  const q = useMarketToday()
  const c = q.data?.current
  return { asOf: c ? `${q.data?.trade_date?.slice(5).replace("-", "/")} ${c.label} 정리` : null }
}

export function MarketTodayBody({ w, h }: WidgetBodyProps) {
  const [slot, setSlot] = useState<string | null>(null)
  const q = useMarketToday(slot)
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!d.current) return <WidgetState empty emptyText={d.next_slot ? `오늘 첫 정리는 ${d.next_slot}에 나와요.` : "아직 장중 정리가 없어요. 평일 09:30·11:30·15:00, 장 마감 뒤 16:00에 만들어집니다."} />
  const c = d.current
  const n = h <= 3 ? 2 : w <= 4 ? 3 : 5
  return <div className="flex h-full min-h-0 flex-col gap-2">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <ToggleGroup type="single" variant="outline" size="sm" value={c.slot} onValueChange={(v) => v && setSlot(v)} aria-label="정리 회차">
        {d.slots.map(s => <ToggleGroupItem key={s.slot} value={s.slot} className="h-7 px-2 text-xs tabular-nums">{s.label}</ToggleGroupItem>)}
      </ToggleGroup>
      <span className="text-[11px] text-muted-foreground tabular-nums">
        {c.market?.kospi && <>코스피 <span className={tone(c.market.kospi.change_pct)}>{formatPercent(c.market.kospi.change_pct)}</span> · </>}
        텔레그램 {c.telegram} · 뉴스 {c.news}{d.next_slot ? ` · 다음 ${d.next_slot}` : ""}
      </span>
    </div>
    <p className="flex items-center gap-1 text-[11px] text-hypothesis"><Sparkles className="size-3" aria-hidden="true" />AI 요약 · 실시간 소스에서 주로 나온 얘기</p>
    {c.topics.length === 0
      ? <p className="text-sm text-muted-foreground">이 회차에는 출처로 확인된 화두가 없어요.</p>
      : <ul className="-mr-2 min-h-0 divide-y overflow-y-auto pr-2">{c.topics.slice(0, n).map(t => <TopicRow key={t.title} t={t} compact={h <= 3} links={c.links_ready} />)}</ul>}
  </div>
}

/** links = 이 회차 내러티브 연결을 계산했는가 — 아니면(Partial) 칩 줄을 그리지 않는다(§9.4) */
function TopicRow({ t, compact, links }: { t: TodayTopic; compact: boolean; links: boolean }) {
  return <li className="space-y-1 py-2 first:pt-0">
    <div className="flex items-baseline gap-2">
      <span className="text-[13px] font-semibold leading-snug">{t.title}</span>
      {t.continuing && <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-normal">이어짐</Badge>}
      <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums" title={t.sources.map(s => s.publisher).join(" · ")}>{t.echo}곳</span>
    </div>
    <p className={cn("text-[12.5px] leading-5 text-muted-foreground", compact && "line-clamp-2")}>{t.body}</p>
    {!compact && <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
      {t.sources.map(s => s.doc_id
        ? <Link key={s.ref} to={`/doc/${s.doc_id}`} className="hover:text-foreground hover:underline">{s.publisher}</Link>
        : s.url ? <a key={s.ref} href={s.url} target="_blank" rel="noreferrer" className="hover:text-foreground hover:underline">{s.publisher}</a>
        : <span key={s.ref}>{s.publisher}</span>)}
    </div>}
    {!compact && links && <NarrativeChipLine items={t.narratives ?? []} />}
  </li>
}
