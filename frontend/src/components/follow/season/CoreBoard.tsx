// 핵심 종목 진행판 (ia-redesign §4.6a ⑦) — 기준별 필터(?core=) · 상태 요약 · 종목 타일(곧 발표 → 발표 완료 → 일정 미정)
// | 오른쪽에 곧 발표(기대 정리 상태·만들기)와 발표 전 기대를 얼마나 맞혔나.
import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { InfoTip } from "@/components/shared/InfoTip"
import { InPlaceMore } from "@/components/shared/Bounded"
import { CoreBadge, H3, Meta, Pp, SHORT_REASON, Section, VERDICT, expectationStatus, mmdd, patchParams } from "@/components/follow/season/seasonUi"
import { useMakeExpectation } from "@/hooks/useTranscripts"
import { coreCounts, coreTiles, type CoreTile, type MomentumSet } from "@/lib/seasonBoard"
import { cn } from "@/lib/utils"
import type { CoreReason, EvalVerdict, SeasonItem, SeasonOverview } from "@/types"

const SHOWN = 35
const REASON_ORDER: CoreReason[] = ["cap", "mention", "holding_chain", "dc_chain", "pinned"]

export function CoreBoard({ d, today, momentum }: { d: SeasonOverview; today: string; momentum: MomentumSet }) {
  const [params, setParams] = useSearchParams()
  const filter = REASON_ORDER.find((r) => r === params.get("core")) ?? "all"
  const all = coreTiles(d.core, d.reported, d.calendar, today, momentum)
  const tiles = filter === "all" ? all : all.filter((t) => t.reasons.includes(filter))
  const n = coreCounts(tiles)
  const reasons = REASON_ORDER.map((r) => ({ r, n: all.filter((t) => t.reasons.includes(r)).length })).filter((x) => x.n > 0)
  const [more, setMore] = useState(false)
  const [cases, setCases] = useState(false)
  return (
    <div className="surface-grid grid grid-cols-1 lg:grid-cols-[1fr_380px]">
      <Section className="min-w-0">
        <h2 className="flex items-center gap-1 text-[15px] font-semibold">
          핵심 종목
          <InfoTip label="핵심 종목 설명">
            핵심 종목은 발표 전 기대(D-7·D-1)와 시장 반응 정리가 자동으로 만들어집니다. 기준 중 하나라도 맞으면 핵심입니다 — {REASON_ORDER.map((r) => d.core.criteria[r]).filter(Boolean).join(" · ")}
          </InfoTip>
          <span className="tabular-nums font-normal text-muted-foreground">{all.length}개</span>
        </h2>
        {all.length === 0 ? <Meta>이번 시즌 핵심 종목이 아직 없습니다.</Meta> : <>
          <ToggleGroup type="single" variant="outline" size="sm" value={filter} aria-label="핵심 기준" className="flex-wrap justify-start"
            onValueChange={(v) => v && setParams((p) => patchParams(p, { core: v === "all" ? null : v }), { replace: true, preventScrollReset: true })}>
            <ToggleGroupItem value="all" className="px-2.5 text-caption">전체 {all.length}</ToggleGroupItem>
            {reasons.map(({ r, n: c }) => <ToggleGroupItem key={r} value={r} className="px-2.5 text-caption">{SHORT_REASON[r]} {c}</ToggleGroupItem>)}
          </ToggleGroup>
          <p className="flex flex-wrap items-center gap-x-1 text-caption text-muted-foreground">
            발표 <b className="tabular-nums text-foreground">{n.reported}</b> · 곧 발표 <b className="tabular-nums text-foreground">{n.upcoming}</b> · 일정 미정 <b className="tabular-nums text-foreground">{n.none}</b>
            <span className="ml-2 inline-flex items-center gap-1"><i className="inline-block size-1.5 rounded-full bg-hypothesis" />모멘텀 후보</span>
          </p>
          {/* 더 보기는 제자리 — 펼치기 직전 높이 그대로, 나머지 타일은 그 안에서 스크롤 */}
          <InPlaceMore open={more}>
            <div className="grid grid-cols-3 gap-px border bg-border sm:grid-cols-5 xl:grid-cols-7">
              {tiles.slice(0, more ? undefined : SHOWN).map((t) => <Tile key={t.ticker} t={t} />)}
            </div>
          </InPlaceMore>
          {tiles.length > SHOWN && (
            <Button variant="ghost" size="sm" className="mx-auto mt-1 flex text-muted-foreground" aria-expanded={more} onClick={() => setMore(!more)}>
              {more ? "접기" : `${tiles.length - SHOWN}개 더 보기`}
            </Button>
          )}
        </>}
      </Section>
      <Section className="min-w-0">
        {/* '사례 전체'도 제자리 — 오른쪽 칸 높이 그대로 안에서 스크롤 */}
        <InPlaceMore open={cases} className="flex-1">
          <div className="flex flex-col gap-2">
            <Upcoming items={d.upcoming} />
            <Evals evals={d.evals} open={cases} onOpenChange={setCases} />
          </div>
        </InPlaceMore>
      </Section>
    </div>
  )
}

function Tile({ t }: { t: CoreTile }) {
  const to = t.state === "reported" && t.transcriptId ? `/follow/transcripts?t=${t.transcriptId}` : `/us/${t.ticker}`
  const sub = t.state === "upcoming" ? <span className="text-muted-foreground">{mmdd(t.date)} 발표</span>
    : t.state === "reported" ? (t.d1 == null ? <span className="text-muted-foreground">반응 대기</span> : <Pp v={t.d1} />)
    : t.state === "waiting" ? <span className="text-muted-foreground">반응 대기</span>
    : <span className="text-muted-foreground">일정 미정</span>
  return (
    <Link to={to} title={`${t.name ?? t.ticker} · ${t.reasons.map((r) => SHORT_REASON[r]).join("·")}`} data-core-tile={t.state}
      className={cn("flex flex-col gap-0.5 bg-card px-2.5 py-2 transition-colors hover:bg-muted", t.state === "upcoming" && "bg-muted/50")}>
      <span className="flex items-center justify-between gap-1">
        <span className="font-mono text-sm font-semibold">{t.ticker}</span>
        {t.momentum && <i className="size-1.5 rounded-full bg-hypothesis" aria-label="모멘텀 후보" />}
      </span>
      <span className="font-mono text-caption tabular-nums">{sub}</span>
    </Link>
  )
}

function Upcoming({ items }: { items: SeasonItem[] }) {
  const make = useMakeExpectation()
  const run = (ticker: string) => make.mutate({ ticker }, {
    onSuccess: () => toast.success(`${ticker} 발표 전 기대를 정리했습니다`),
    onError: (e) => toast.error(e.message),
  })
  return (
    <div className="flex flex-col gap-1">
      <H3>곧 발표 <span className="tabular-nums font-normal text-muted-foreground">{items.length}</span></H3>
      {items.length === 0 ? <Meta>예정된 발표가 없습니다.</Meta> : (
        <ul className="flex flex-col">
          {items.map((it) => {
            const busy = make.isPending && make.variables?.ticker === it.ticker
            return (
              <li key={it.ticker} className="grid grid-cols-[52px_40px_1fr_auto] items-center gap-x-2 border-t py-1.5 text-sm first:border-t-0">
                <Link to={`/us/${it.ticker}`} className="font-mono font-semibold hover:underline" title={it.name ?? it.ticker}>{it.ticker}</Link>
                <span className="tabular-nums text-muted-foreground">{mmdd(it.event_date)}</span>
                <span className="flex min-w-0 items-center gap-1.5 truncate text-caption text-muted-foreground"><CoreBadge core={it.core} />{expectationStatus(it.expectation)}</span>
                {!it.expectation?.qualitative ? (
                  <Button variant="ghost" size="xs" onClick={() => run(it.ticker)} disabled={make.isPending}>
                    {busy && <Spinner className="size-3" />} 기대 정리 만들기
                  </Button>
                ) : <span />}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

const EVAL_KEYS: Exclude<EvalVerdict, "minor">[] = ["hit", "underweighted", "noise", "missed"]
const EVAL_CLS: Record<Exclude<EvalVerdict, "minor">, string> = { hit: "bg-chart-green", underweighted: "bg-hypothesis/60", noise: "bg-muted-foreground/40", missed: "bg-hypothesis" }

function Evals({ evals, open, onOpenChange }: { evals: SeasonOverview["evals"]; open: boolean; onOpenChange: (v: boolean) => void }) {
  const total = EVAL_KEYS.reduce((n, k) => n + evals[k], 0)
  const missed = evals.cases.filter((c) => c.verdict === "missed")
  return (
    <div className="flex flex-col gap-2 border-t pt-3">
      <H3>발표 전 기대를 얼마나 맞혔나 <span className="tabular-nums font-normal text-muted-foreground">{total}건</span></H3>
      {total === 0 ? <Meta>아직 채점된 발표가 없습니다.</Meta> : <>
        <div className="flex h-2 w-full overflow-hidden" role="img" aria-label={EVAL_KEYS.map((k) => `${VERDICT[k]} ${evals[k]}`).join(", ")}>
          {EVAL_KEYS.map((k) => evals[k] > 0 && <span key={k} className={EVAL_CLS[k]} style={{ width: `${(evals[k] / total) * 100}%` }} />)}
        </div>
        <p className="flex flex-wrap gap-x-2 text-caption">
          {EVAL_KEYS.map((k) => <span key={k} className="inline-flex items-center gap-1"><i className={cn("inline-block size-2", EVAL_CLS[k])} />{VERDICT[k]} <b className="tabular-nums">{evals[k]}</b></span>)}
        </p>
        {missed.length > 0 && <p className="text-caption text-muted-foreground">못 봄 · {missed.slice(0, 2).map((c) => `${c.ticker} ${c.issue}`).join(" / ")}</p>}
        <Collapsible open={open} onOpenChange={onOpenChange}>
          <CollapsibleTrigger asChild><Button variant="ghost" size="xs" className="group text-muted-foreground">
            <span className="group-data-[state=open]:hidden">사례 전체 ›</span><span className="hidden group-data-[state=open]:inline">접기</span>
          </Button></CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="flex flex-col gap-1 pt-1 text-caption">
              {evals.cases.map((c, i) => <li key={`${c.ticker}-${i}`}><b className="font-mono">{c.ticker}</b> · {VERDICT[c.verdict]} · <span className="text-muted-foreground">{c.issue}</span></li>)}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      </>}
    </div>
  )
}
