// 이번 시즌 시장이 따진 것 (ia-redesign §4.6a ④) — 섹터 줄 = 섹터명·판정·모멘텀 n | 요약 한 줄 | 반응 분포 점 띠 | 발표 수 | ›.
// 줄 전체가 섹터 상세 링크. 정렬은 ?ssort=, 요약 없는 섹터는 '그 밖의 섹터 ›'로 접는다.
import { Link, useSearchParams } from "react-router-dom"
import { ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { InfoTip } from "@/components/shared/InfoTip"
import { Meta, Section, VerdictBadge, patchParams } from "@/components/follow/season/seasonUi"
import { DOT_RANGE, SECTOR_SORTS, sectorRows, type MomentumSet, type SectorSort } from "@/lib/seasonBoard"
import { cn } from "@/lib/utils"
import { formatPp } from "@/utils/format"
import type { SeasonOverview } from "@/types"

type Row = ReturnType<typeof sectorRows>["main"][number]

export function SeasonSectors({ d, momentum }: { d: SeasonOverview; momentum: MomentumSet }) {
  const [params, setParams] = useSearchParams()
  const sort: SectorSort = SECTOR_SORTS.find((s) => s.value === params.get("ssort"))?.value ?? "verdict"
  const { main, rest } = sectorRows(d.sectors, d.reported, momentum, sort)
  const season = params.get("season")
  const href = (key: string) => {
    const p = new URLSearchParams({ view: "season", sector: key })
    if (season) p.set("season", season)
    return `/follow/transcripts?${p}`
  }
  const row = (s: Row) => (
    <Link key={s.key} to={href(s.key)} data-sector-row={s.key}
      className="grid grid-cols-1 items-center gap-x-4 gap-y-1.5 border-t px-2 py-3 transition-colors first:border-t-0 hover:bg-muted/60 md:grid-cols-[minmax(150px,200px)_1fr_minmax(180px,240px)_40px_16px]">
      <span className="flex flex-col items-start gap-1">
        <span className="font-semibold">{s.name}</span>
        <span className="flex flex-wrap gap-1">
          <VerdictBadge verdict={s.verdict} />
          {s.momentum > 0 && <Badge variant="outline" className="border-hypothesis/40 font-normal text-hypothesis">모멘텀 {s.momentum}</Badge>}
        </span>
      </span>
      <span className="line-clamp-2 text-sm">{s.one_line ?? <span className="text-muted-foreground">요약 전 · 반응 정리 {s.n_reactions}/{s.n_reported}</span>}</span>
      <DotBand dots={s.dots} />
      <span className="text-sm tabular-nums text-muted-foreground md:text-right">{s.n_reported}<span className="md:hidden">곳 발표</span></span>
      <ChevronRight className="hidden size-4 text-muted-foreground md:block" aria-hidden="true" />
    </Link>
  )
  return (
    <Section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1 text-[15px] font-semibold">
          이번 시즌 시장이 따진 것
          <InfoTip label="시장이 따진 것 설명">
            섹터별로 시장이 이번 실적에서 무엇을 반기고 문제 삼았는지 요약합니다. 점 하나는 발표한 종목의 첫 거래일 업종 ETF 대비 %p이고, 눈금은 ±{DOT_RANGE}%p로 고정합니다. 줄을 누르면 섹터 상세로 갑니다.
          </InfoTip>
        </h2>
        <ToggleGroup type="single" variant="outline" size="sm" value={sort} aria-label="섹터 정렬"
          onValueChange={(v) => v && setParams((p) => patchParams(p, { ssort: v === "verdict" ? null : v }), { replace: true, preventScrollReset: true })}>
          {SECTOR_SORTS.map((s) => <ToggleGroupItem key={s.value} value={s.value} className="px-2.5 text-caption">{s.label}</ToggleGroupItem>)}
        </ToggleGroup>
      </div>
      {d.sectors.length === 0 ? <Meta>이번 시즌 발표한 섹터가 아직 없습니다.</Meta> : (
        <div className="flex flex-col">
          <div className="hidden grid-cols-[minmax(150px,200px)_1fr_minmax(180px,240px)_40px_16px] gap-x-4 border-b px-2 pb-1.5 text-caption text-muted-foreground md:grid">
            <span>섹터 · 판정</span><span>시장이 본 것</span>
            <span className="flex justify-between"><span>−{DOT_RANGE}%p</span><span>첫 거래일 업종 대비</span><span>+{DOT_RANGE}%p</span></span>
            <span className="text-right">발표</span><span />
          </div>
          {main.map(row)}
          {rest.length > 0 && (
            <Collapsible>
              <CollapsibleContent className="flex flex-col border-t">{rest.map(row)}</CollapsibleContent>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="group mx-auto mt-1 flex text-muted-foreground">
                  <span className="group-data-[state=open]:hidden">그 밖의 섹터 {rest.length}개 ›</span>
                  <span className="hidden group-data-[state=open]:inline">접기</span>
                </Button>
              </CollapsibleTrigger>
            </Collapsible>
          )}
        </div>
      )}
    </Section>
  )
}

/** 양끝 라벨이 띠 밖으로 나가지 않게 — 왼쪽 끝은 오른쪽으로, 오른쪽 끝은 왼쪽으로 붙인다 */
const edgeLabel = (x: number) => ({ left: `${x * 100}%`, transform: `translateX(${x < 0.12 ? 0 : x > 0.88 ? -100 : -50}%)` })

/** 반응 분포 점 띠 — 가운데 0, 양끝 종목 이름. 점에 마우스를 올리면 실제 값 */
function DotBand({ dots }: { dots: Row["dots"] }) {
  if (!dots.length) return <span className="text-caption text-muted-foreground">집계 전</span>
  const lo = dots[0], hi = dots[dots.length - 1]
  return (
    <span className="relative block h-8" aria-label={`첫 거래일 업종 대비 ${formatPp(lo.v, 1)} ~ ${formatPp(hi.v, 1)}`}>
      <span className="absolute inset-x-0 top-5 h-px bg-border" />
      <span className="absolute left-1/2 top-3.5 h-3 w-px bg-muted-foreground" />
      {dots.map((p) => (
        <span key={p.ticker} title={`${p.ticker} ${formatPp(p.v, 1)}`} style={{ left: `${p.x * 100}%` }}
          className={cn("absolute top-[17px] size-1.5 -translate-x-1/2 rounded-full", p.v > 0 ? "bg-up" : p.v < 0 ? "bg-down" : "bg-muted-foreground")} />
      ))}
      <span style={edgeLabel(lo.x)} className="absolute top-0 font-mono text-[10px] text-muted-foreground">{lo.ticker}</span>
      {dots.length > 1 && <span style={edgeLabel(hi.x)} className="absolute top-0 font-mono text-[10px] text-muted-foreground">{hi.ticker}</span>}
    </span>
  )
}
