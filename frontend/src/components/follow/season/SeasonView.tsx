// 실적 시즌 보고서 (?view=season) — 시즌 → 섹터 → 콜 3단의 첫 단 (docs/specs/earnings-season.md §시즌 보고서)
import { Link, useSearchParams } from "react-router-dom"
import { ChevronDown } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { QueryState } from "@/components/shared/QueryState"
import { CallMomentumPanel } from "@/components/follow/CallMomentumPanel"
import { useMakeExpectation, useSeason } from "@/hooks/useTranscripts"
import { formatPercent } from "@/utils/format"
import { Bullets, Cols, CoreBadge, Meta, Pp, SHORT_REASON, Section, VERDICT, VerdictBadge, mmdd } from "@/components/follow/season/seasonUi"
import type { CoreReason, EvalVerdict, SeasonItem, SeasonOverview } from "@/types"

/** 종목 → 콜 상세(?t=). 녹취록이 없으면 굵은 글자만 */
/** 종목 → 회사 상세(도시에: 무슨 회사·차트·기술적 분석·실적 발표 카드). 반응 한 줄은 콜 상세로 */
function Ticker({ it }: { it: Pick<SeasonItem, "ticker" | "transcript_id" | "name"> }) {
  return <Link to={`/us/${it.ticker}`} className="font-semibold hover:underline" title={it.name ? `${it.name} — 회사 상세` : "회사 상세"}>{it.ticker}</Link>
}

export function SeasonView() {
  const [params] = useSearchParams()
  const season = params.get("season")
  const q = useSeason(season)
  // 갱신 실패·오프라인이어도 이전 결과를 유지한다(QueryState 규약, docs/specs/frontend-api-reliability.md)
  return <QueryState query={q} loading={<SeasonSkeleton />} isEmpty={() => false}>{(d) => <SeasonBody d={d} season={season} />}</QueryState>
}

function SeasonBody({ d, season }: { d: SeasonOverview; season: string | null }) {
  return (
    <div className="space-y-4">
      <Header d={d} />
      {/* 시장이 무엇에 돈을 냈나가 먼저 — 실망 목록보다 중요(2026-10-31) */}
      <Cols>
        <Section title="반응이 좋았던 발표" note="첫 거래일 업종 ETF 대비 높은 순">
          {d.top_up.length ? <Bullets items={d.top_up.map((it) => <>
            <Ticker it={it} /> <span className="text-muted-foreground">{it.sector_name}</span> · <Pp v={it.d1} />
            {it.latest != null && it.latest_date && it.latest !== it.d1 && <> → <Pp v={it.latest} /></>}
            {it.follow && <span className="text-muted-foreground"> · {it.follow}</span>}
            {it.eps_surprise != null && <span className="text-caption text-muted-foreground"> · EPS {formatPercent(it.eps_surprise)}</span>}
            {it.headline && (it.transcript_id
              ? <Link to={`/follow/transcripts?t=${it.transcript_id}`} className="block text-caption text-muted-foreground hover:text-foreground hover:underline">{it.headline}</Link>
              : <span className="block text-caption text-muted-foreground">{it.headline}</span>)}
          </>)} /> : <Meta>첫 거래일에 업종보다 강했던 발표가 아직 없습니다.</Meta>}
          <Meta>%p = 발표 후 첫 거래일까지 업종 ETF 대비 → 최근 거래일까지 누적. 종목을 누르면 회사 상세, 한 줄 요약을 누르면 콜 상세.</Meta>
        </Section>
        <Section title="실적은 아쉬웠는데 주가는 올랐다" note="EPS 컨센서스 하회 · 첫 거래일 업종 대비 상승">
          {d.miss_up.length ? <Bullets items={d.miss_up.map((it) => <>
            <Ticker it={it} /> EPS <span className="tabular-nums text-down">{formatPercent(it.eps_surprise)}</span> 하회 → <Pp v={it.d1} />
            {it.follow && <span className="text-muted-foreground"> · {it.follow}</span>}
            {it.eps_surprise != null && Math.abs(it.eps_surprise) > 200 && <span className="text-caption text-muted-foreground"> (EPS 숫자 왜곡 가능)</span>}
          </>)} /> : <Meta>EPS가 컨센서스에 못 미쳤는데 업종보다 강했던 발표가 아직 없습니다.</Meta>}
          <Meta>악재가 이미 주가에 반영됐거나, 시장이 숫자 말고 다른 것(가이던스·수주·구조 변화)을 본 경우. EPS는 GAAP·조정 기준이 섞여 참고용.</Meta>
        </Section>
      </Cols>
      <SectorList d={d} season={season} />
      <Cols>
        <Section title="실적은 좋았는데 주가는 약했다">
          {d.beat_down.length ? <Bullets items={d.beat_down.map((it) => <>
            <Ticker it={it} /> EPS <span className="tabular-nums text-up">{formatPercent(it.eps_surprise)}</span> 상회 → <Pp v={it.d1} />
            {it.eps_surprise != null && Math.abs(it.eps_surprise) > 200 && <span className="text-caption text-muted-foreground"> (EPS 숫자 왜곡 가능)</span>}
          </>)} /> : <Meta>컨센서스를 넘고도 첫 거래일에 업종보다 약했던 종목이 아직 없습니다.</Meta>}
          <Meta>EPS는 GAAP·조정 기준이 섞여 참고용.</Meta>
        </Section>
        <Section title="첫 반응이 뒤집히거나 되돌려졌다">
          {d.reversed.length ? <Bullets items={d.reversed.map((it) => <>
            <Ticker it={it} /> <Pp v={it.d1} /> → <Pp v={it.latest} />{it.follow && <span className="text-muted-foreground"> · {it.follow}</span>}
          </>)} /> : <Meta>첫 반응이 뒤집히거나 낙폭 절반 이상 되돌려진 종목이 아직 없습니다.</Meta>}
          <Meta>첫 거래일 → 최근 거래일까지 누적.</Meta>
        </Section>
      </Cols>
      <Cols>
        <Upcoming items={d.upcoming} />
        <Evals evals={d.evals} />
      </Cols>
      <CoreCard core={d.core} />
      <Section title="새 모멘텀 후보" note="직전 실적 발표 대비 새로 생기거나 빨라진 성장 동인">
        <CallMomentumPanel />
      </Section>
    </div>
  )
}

function Header({ d }: { d: SeasonOverview }) {
  const c = d.counts
  const ch = d.changes
  const parts = [
    ch.reactions.length ? `반응 추가: ${ch.reactions.join("·")}` : null,
    ch.themes.length ? `섹터 요약 갱신: ${ch.themes.join("·")}` : null,
    ch.expectations.length ? `발표 전 기대: ${ch.expectations.join("·")}` : null,
    ch.transcripts.length ? `새 녹취록: ${ch.transcripts.join("·")}` : null,
  ].filter(Boolean)
  return (
    <Section title={d.season.label} note={`${mmdd(d.season.start)}부터 · 매일 07:20 갱신`}>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
        <span>발표 <b className="text-[15px] tabular-nums text-foreground">{c.reported}</b> / {c.followed}</span>
        <span>첫 거래일 업종보다 강했다 <b className="text-[15px] tabular-nums text-up">{c.up}</b> / {c.reported}</span>
        <span>컨센서스 하회에도 주가 강세 <b className="text-[15px] tabular-nums text-up">{c.miss_up}</b> / {c.miss}</span>
        <span>컨센서스 상회에도 주가 약세 <b className="text-[15px] tabular-nums text-down">{c.beat_down}</b> / {c.beat}</span>
        <span>첫 반응이 뒤집힘 <b className="text-[15px] tabular-nums text-foreground">{c.reversed}</b></span>
        <span>반응 정리 <b className="text-[15px] tabular-nums text-foreground">{c.reactions}</b> (확정 {c.reactions_final})</span>
      </div>
      <Meta><b className="text-foreground">오늘 바뀐 것</b> · {parts.length ? parts.join(" · ") : "오늘 바뀐 것 없음"}</Meta>
    </Section>
  )
}

function SectorList({ d, season }: { d: SeasonOverview; season: string | null }) {
  const href = (key: string) => {
    const p = new URLSearchParams({ view: "season", sector: key })
    if (season) p.set("season", season)
    return `/follow/transcripts?${p}`
  }
  // AI 데이터센터 밸류체인·섹터 요약이 있는 섹터를 먼저, 나머지(대개 종목 한두 개짜리)는 접어 둔다
  const main = d.sectors.filter((s) => s.dc_chain || s.verdict)
  const rest = d.sectors.filter((s) => !s.dc_chain && !s.verdict)
  const row = (s: SeasonOverview["sectors"][number]) => (
            <Button key={s.key} variant="ghost" asChild
              className="h-auto w-full justify-start rounded-none border-t px-2 py-2.5 text-left font-normal whitespace-normal first:border-t-0">
              <Link to={href(s.key)} className="grid grid-cols-1 items-baseline gap-x-4 gap-y-1 md:grid-cols-[minmax(150px,200px)_1fr_auto]">
                <span className="flex flex-wrap items-baseline gap-1.5 font-semibold">{s.name} <VerdictBadge verdict={s.verdict} /></span>
                <span className="text-sm">{s.one_line ?? <span className="text-muted-foreground">반응 정리 {s.n_reactions}/{s.n_reported} — 숫자만 있습니다</span>}</span>
                <span className="text-caption text-muted-foreground md:whitespace-nowrap">
                  {s.tickers.map((t, i) => <span key={t.ticker}>{i > 0 && " · "}{t.ticker} <Pp v={t.d1} /></span>)} ›
                </span>
              </Link>
            </Button>
  )
  return (
    <Section title="이번 시즌 시장이 따진 것" note="섹터를 누르면 섹터 상세로">
      {d.sectors.length === 0 ? <Meta>이번 시즌 발표한 섹터가 아직 없습니다.</Meta> : (
        <div className="flex flex-col">
          {main.map(row)}
          {rest.length > 0 && (
            <Collapsible>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="mt-1 w-fit text-muted-foreground">그 밖의 섹터 {rest.length}개 ›</Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="flex flex-col">{rest.map(row)}</CollapsibleContent>
            </Collapsible>
          )}
        </div>
      )}
      <Meta>%p = 발표 후 첫 거래일까지 업종 ETF 대비 초과수익</Meta>
    </Section>
  )
}

/** 발표 전 기대 준비 상태 — qualitative는 정성 정리(쟁점·기준)까지 있는지 */
function expectationStatus(e: SeasonItem["expectation"]) {
  if (!e) return "기대 정리 전"
  if (e.qualitative) return e.d1 ? "전날 기대 정리됨" : "일주일 전 기대 정리됨"
  return e.d1 || e.d7 ? "숫자만" : "기대 정리 전"
}

function Upcoming({ items }: { items: SeasonItem[] }) {
  const make = useMakeExpectation()
  const run = (ticker: string) => make.mutate({ ticker }, {
    onSuccess: () => toast.success(`${ticker} 발표 전 기대를 정리했습니다`),
    onError: (e) => toast.error(e.message),
  })
  return (
    <Section title="곧 발표">
      {items.length === 0 ? <Meta>예정된 발표가 없습니다.</Meta> : (
        <ul className="flex list-disc flex-col gap-1 pl-5 text-sm marker:text-muted-foreground">
          {items.map((it) => {
            const busy = make.isPending && make.variables?.ticker === it.ticker
            return (
              <li key={it.ticker}>
                <span className="inline-flex flex-wrap items-center gap-1.5">
                  <Ticker it={it} /> <span className="tabular-nums">{mmdd(it.event_date)}</span>
                  <CoreBadge core={it.core} />
                  <span className="text-muted-foreground">· {expectationStatus(it.expectation)}</span>
                  {!it.expectation?.qualitative && (
                    <Button variant="ghost" size="xs" onClick={() => run(it.ticker)} disabled={make.isPending}
                      title="발표 전 기대(쟁점·호재/악재 기준)를 지금 만듭니다 — 1~2분">
                      {busy && <Spinner className="size-3" />} 기대 정리 만들기
                    </Button>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </Section>
  )
}

function Evals({ evals }: { evals: SeasonOverview["evals"] }) {
  const keys: Exclude<EvalVerdict, "minor">[] = ["hit", "underweighted", "noise", "missed"]
  const total = keys.reduce((n, k) => n + evals[k], 0)
  return (
    <Section title="발표 전 기대를 얼마나 맞혔나">
      {total === 0 ? <Meta>아직 채점된 발표가 없습니다 — 발표 전 기대가 정리된 종목의 반응이 확정되면 채점됩니다.</Meta> : (
        <Bullets items={keys.map((k) => {
          const ex = evals.cases.filter((c) => c.verdict === k).slice(0, 2)
          return <>{VERDICT[k]} <b className="tabular-nums">{evals[k]}</b>{ex.length > 0 && <span className="text-muted-foreground">: {ex.map((c) => `${c.ticker} ${c.issue}`).join(", ")}</span>}</>
        })} />
      )}
    </Section>
  )
}

function CoreCard({ core }: { core: SeasonOverview["core"] }) {
  const reasons = Object.keys(core.criteria) as CoreReason[]
  const count = (r: CoreReason) => core.tickers.filter((t) => t.reasons.includes(r)).length
  return (
    <Section title="핵심 종목" note={`${core.tickers.length}개`}>
      <Bullets items={[
        "핵심 종목은 발표 전 기대(D-7·D-1)와 시장 반응 정리가 자동으로 만들어집니다. 아래 기준 중 하나라도 맞으면 핵심입니다.",
        ...reasons.map((r) => <>{core.criteria[r]} <span className="tabular-nums text-muted-foreground">· {count(r)}개</span></>),
      ]} />
      {core.tickers.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="group w-fit">
              <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" /> 종목 모두 보기
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {core.tickers.map((t) => (
                <Badge key={t.ticker} variant="outline" className="h-auto gap-1 font-normal" title={t.name ?? undefined}>
                  <span className="font-semibold">{t.ticker}</span>
                  <span className="text-[10px] text-muted-foreground">{t.reasons.map((r) => SHORT_REASON[r]).join("·")}</span>
                </Badge>
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}
    </Section>
  )
}

function SeasonSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-busy="true" aria-label="실적 시즌 불러오는 중">
      <Skeleton className="h-24 w-full rounded-card" />
      <Skeleton className="h-64 w-full rounded-card" />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2"><Skeleton className="h-40 rounded-card" /><Skeleton className="h-40 rounded-card" /></div>
    </div>
  )
}
