// 반응 보드 (ia-redesign §4.6a ⑤ 왼쪽) — 반응이 좋았던 발표(기본 탭) · 숫자와 반대로 · 뒤집혔다. 탭은 ?rtab=.
// 줄: 종목 · 첫 거래일 → 최근 · 후속 · EPS · 섹터 · 모멘텀/핵심 배지 · 한 줄 요약(→ 콜 상세)
import { Link, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { InfoTip } from "@/components/shared/InfoTip"
import { CoreBadge, Meta, Pp, Section, patchParams } from "@/components/follow/season/seasonUi"
import { reactionLists, type MomentumSet, type ReactionTab } from "@/lib/seasonBoard"
import { formatPercent } from "@/utils/format"
import type { SeasonItem, SeasonOverview } from "@/types"

const TABS: { value: ReactionTab; label: string; empty: string }[] = [
  { value: "good", label: "좋았다", empty: "첫 거래일에 업종보다 강했던 발표가 아직 없습니다." },
  { value: "opposite", label: "숫자와 반대로", empty: "실적 숫자와 반대로 움직인 발표가 아직 없습니다." },
  { value: "reversed", label: "뒤집혔다", empty: "첫 반응이 뒤집히거나 되돌려진 발표가 아직 없습니다." },
]
const SHOWN = 9

export function ReactionBoard({ d, momentum }: { d: SeasonOverview; momentum: MomentumSet }) {
  const [params, setParams] = useSearchParams()
  const tab: ReactionTab = TABS.find((t) => t.value === params.get("rtab"))?.value ?? "good"
  const lists = reactionLists(d.reported)
  return (
    <Section className="min-w-0">
      <h2 className="flex items-center gap-1 text-[15px] font-semibold">
        반응이 좋았던 발표
        <InfoTip label="반응 보드 설명">
          %p는 발표 후 첫 거래일 업종 ETF 대비 초과수익이고, 화살표 뒤는 최근 거래일까지 누적입니다. '숫자와 반대로'는 EPS가 컨센서스를 밑돌았는데 강했거나 웃돌았는데 약했던 발표입니다. EPS는 GAAP·조정 기준이 섞여 참고용입니다.
        </InfoTip>
      </h2>
      <Tabs value={tab} onValueChange={(v) => setParams((p) => patchParams(p, { rtab: v === "good" ? null : v }), { replace: true, preventScrollReset: true })}>
        <TabsList>
          {TABS.map((t) => <TabsTrigger key={t.value} value={t.value}>{t.label} <span className="tabular-nums text-muted-foreground">{lists[t.value].length}</span></TabsTrigger>)}
        </TabsList>
        {TABS.map((t) => (
          <TabsContent key={t.value} value={t.value} className="pt-1">
            {lists[t.value].length === 0 ? <Meta className="py-2">{t.empty}</Meta> : <>
              <div className="flex flex-col">{lists[t.value].slice(0, SHOWN).map((it) => <ReactionRow key={it.ticker} it={it} momentum={momentum} />)}</div>
              {lists[t.value].length > SHOWN && (
                <Collapsible>
                  <CollapsibleContent className="flex flex-col border-t">
                    {lists[t.value].slice(SHOWN).map((it) => <ReactionRow key={it.ticker} it={it} momentum={momentum} />)}
                  </CollapsibleContent>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" size="sm" className="group mx-auto mt-1 flex text-muted-foreground">
                      <span className="group-data-[state=open]:hidden">{lists[t.value].length - SHOWN}곳 더 보기</span>
                      <span className="hidden group-data-[state=open]:inline">접기</span>
                    </Button>
                  </CollapsibleTrigger>
                </Collapsible>
              )}
            </>}
          </TabsContent>
        ))}
      </Tabs>
    </Section>
  )
}

function ReactionRow({ it, momentum }: { it: SeasonItem; momentum: MomentumSet }) {
  const m = momentum.byTicker.get(it.ticker)
  const eps = it.eps_surprise
  return (
    <div className="grid grid-cols-[56px_1fr] gap-x-3 border-t py-2.5 first:border-t-0">
      <Link to={`/us/${it.ticker}`} className="font-mono text-sm font-semibold hover:underline" title={it.name ?? it.ticker}>{it.ticker}</Link>
      <div className="min-w-0 space-y-0.5">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span><Pp v={it.d1} className="font-semibold" />{it.latest != null && it.latest_date && it.latest !== it.d1 && <> → <Pp v={it.latest} /></>}</span>
          {it.follow && <span className="text-caption text-muted-foreground">{it.follow}</span>}
          {eps != null && <span className="text-caption text-muted-foreground">EPS {formatPercent(eps)}{Math.abs(eps) > 200 ? " (왜곡 가능)" : ""}</span>}
          <span className="text-caption text-muted-foreground">{it.sector_name}</span>
          <CoreBadge core={it.core} />
          {m && <Badge variant="outline" className="border-hypothesis/40 font-normal text-hypothesis">모멘텀</Badge>}
        </p>
        {it.headline && (it.transcript_id
          ? <Link to={`/follow/transcripts?t=${it.transcript_id}`} className="block text-caption text-muted-foreground hover:text-foreground hover:underline">{it.headline}</Link>
          : <p className="text-caption text-muted-foreground">{it.headline}</p>)}
      </div>
    </div>
  )
}
