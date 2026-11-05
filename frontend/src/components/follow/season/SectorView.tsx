// 섹터 상세 (?view=season&sector=<키>[&season=]) — 시즌 → 섹터 → 콜 3단의 가운데 (docs/specs/earnings-season.md §섹터 상세)
import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { QueryState } from "@/components/shared/QueryState"
import { InfoTip } from "@/components/shared/InfoTip"
import { useComputeCallReaction, useSeasonSector } from "@/hooks/useTranscripts"
import { formatPp } from "@/utils/format"
import { Bullets, Cols, CoreBadge, Meta, Pp, Section, VerdictBadge, mmdd, seasonLabel } from "@/components/follow/season/seasonUi"
import type { SectorDetail } from "@/types"

/** 종목별 선 색 — 테마 차트 토큰만 */
const LINE_COLORS = ["var(--color-chart-1)", "var(--color-chart-3)", "var(--color-chart-4)", "var(--color-chart-2)",
  "var(--color-chart-5)", "var(--color-chart-red)", "var(--color-chart-gray)", "var(--color-chart-yellow)"]
const TOOLTIP_STYLE = { fontSize: 12, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" }

export function SectorView({ sectorKey }: { sectorKey: string }) {
  const [params, setParams] = useSearchParams()
  const season = params.get("season")
  const q = useSeasonSector(sectorKey, season)

  const back = new URLSearchParams({ view: "season" })
  if (season) back.set("season", season)
  const crumb = (name?: string) => (
    <div className="flex flex-wrap items-center gap-1.5 text-caption text-muted-foreground">
      <Link to={`/follow/transcripts?${back}`} className="text-primary hover:underline">실적 시즌</Link> › <span>{name ?? sectorKey}</span>
    </div>
  )

  const pickSeason = (s: string) => {
    if (!s) return
    setParams((prev) => { const n = new URLSearchParams(prev); n.set("season", s); return n }, { replace: true })
  }
  // 갱신 실패·오프라인이어도 이전 결과를 유지한다(QueryState 규약)
  return (
    <QueryState query={q} isEmpty={() => false}
      loading={<div className="space-y-4">{crumb()}<Skeleton className="h-72 w-full rounded-card" /><Skeleton className="h-48 w-full rounded-card" /></div>}>
      {(d) => <SectorBody d={d} crumb={crumb} pickSeason={pickSeason} />}
    </QueryState>
  )
}

function SectorBody({ d, crumb, pickSeason }: { d: SectorDetail; crumb: (name?: string) => ReactNode; pickSeason: (s: string) => void }) {
  const body = d.theme?.body

  return (
    <div className="space-y-4">
      <Section>
        {crumb(d.name)}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex flex-wrap items-baseline gap-2 text-[17px] font-semibold">{d.name} <VerdictBadge verdict={d.theme?.verdict} /></h2>
          {/* 시즌 탭 — 오래된 시즌 → 최신이 오른쪽 (API가 이미 오래된 순) */}
          {d.seasons.length > 1 && (
            <ToggleGroup type="single" variant="outline" size="sm" value={d.season} onValueChange={pickSeason} aria-label="시즌" className="flex-wrap">
              {d.seasons.map((s) => <ToggleGroupItem key={s} value={s} className="px-2.5 text-caption">{seasonLabel(s)}</ToggleGroupItem>)}
            </ToggleGroup>
          )}
        </div>
        <Meta>{d.members.map((m) => m.ticker).join(" · ")} · 비교: {d.etf}{d.theme && ` · ${mmdd(d.theme.created_at)} 요약`}</Meta>
        {body?.one_line && <p className="text-[15px] font-semibold">{body.one_line}</p>}
        <TimelineChart t={d.timeline} etf={d.etf} companies={d.companies} />
      </Section>

      <Cols>
        <Section title="시장이 반긴 것 / 문제 삼은 것">
          {body && (body.welcomed?.length || body.questioned?.length) ? <>
            {!!body.welcomed?.length && <><h3 className="text-sm font-semibold">반긴 것</h3><Bullets items={body.welcomed} /></>}
            {!!body.questioned?.length && <><h3 className="mt-2 text-sm font-semibold">문제 삼은 것</h3><Bullets items={body.questioned} /></>}
          </> : <Meta>섹터 요약 전입니다.</Meta>}
        </Section>
        <Companies companies={d.companies} />
      </Cols>

      {(d.theme_history.length > 0 || !!body?.next?.length) && (
        <Cols>
          <Section title="이번 시즌 해석이 바뀐 과정">
            {d.theme_history.length
              ? <Bullets items={d.theme_history.map((t) => `${mmdd(t.created_at)} · ${t.body.change_note || t.body.one_line || "-"}`)} />
              : <Meta>요약 이력이 아직 없습니다.</Meta>}
          </Section>
          <Section title="다음에 볼 것">
            {body?.next?.length ? <Bullets items={body.next} /> : <Meta>아직 없습니다.</Meta>}
          </Section>
        </Cols>
      )}

      {d.history.length > 0 && (
        <Section title={<span className="inline-flex items-center gap-1">지난 시즌과 비교<InfoTip label="지난 시즌 비교 설명">시즌별 발표 후 첫 거래일 {d.etf} 대비 %p입니다. 모든 시즌을 같은 눈금(±20%p)으로 그리고, 시즌은 발표 시점 기준입니다.</InfoTip></span>}>
          <div className="surface-grid grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))]">
            {d.history.map((h) => <SeasonBars key={h.season} h={h} />)}
          </div>
          {!!body?.vs_last_season?.length && <Bullets items={body.vs_last_season} />}
        </Section>
      )}
    </div>
  )
}

const DAY = 86_400_000
const toX = (d: string) => Date.parse(`${d}T00:00:00Z`)
const xLabel = (v: number) => mmdd(new Date(v).toISOString().slice(0, 10))

/** 시즌 한 달을 같은 달력 축에 — 업종 ETF 대비 누적 %p(창 첫 거래일 = 0), 종목별 발표일은 세로선 */
function TimelineChart({ t, etf, companies }: { t: SectorDetail["timeline"]; etf: string; companies: SectorDetail["companies"] }) {
  const entries = Object.entries(t.series)
  if (!t.start || !entries.length) return <Meta>이번 시즌 소속 종목의 시세가 아직 없습니다.</Meta>
  // 반응이 갈린 종목만 색 — 첫 거래일 반응이 가장 강한 둘·가장 약한 둘, 나머지는 회색(§4.6 섹터 상세 ②)
  const ranked = companies.filter((c) => c.d1 != null).sort((a, b) => (b.d1 as number) - (a.d1 as number)).map((c) => c.ticker)
  const accent = ranked.length <= 4 ? ranked : [...ranked.slice(0, 2), ...ranked.slice(-2)]
  const colorOf = new Map(accent.map((tk, i) => [tk, LINE_COLORS[i % LINE_COLORS.length]]))
  const GRAY = "var(--color-chart-gray)"
  const color = (ticker: string) => colorOf.get(ticker) ?? GRAY
  const ordered = [...entries].sort((a, b) => Number(colorOf.has(a[0])) - Number(colorOf.has(b[0])))   // 색 선을 위에
  // 선 끝 라벨 겹침 피하기 — 이미 쓴 y와 11px 안이면 아래로 민다(그리는 순서대로, 첫 선에서 새로 센다 — 차트가 혼자 다시 그려도 쌓이지 않게)
  const usedY: number[] = []
  const labelY = (ticker: string, y: number) => {
    if (ticker === ordered[0]?.[0]) usedY.length = 0
    let v = y
    while (usedY.some((u) => Math.abs(u - v) < 11)) v += 11
    usedY.push(v)
    return v
  }
  // 같은 날 발표한 종목은 세로선 하나에 묶는다
  const byDate = new Map<string, string[]>()
  for (const [ticker, day] of Object.entries(t.events).sort((a, b) => a[1].localeCompare(b[1]))) byDate.set(day, [...(byDate.get(day) ?? []), ticker])
  const lo = toX(t.start), hi = toX(t.view_end ?? t.end ?? t.start)
  const ticks = Array.from({ length: Math.floor((hi - lo) / (7 * DAY)) + 1 }, (_, i) => lo + i * 7 * DAY)
  return (
    <div className="space-y-1">
      <h3 className="flex items-center gap-1 text-sm font-semibold">
        시즌 주가 흐름
        <InfoTip label="시즌 주가 흐름 설명">{etf} 대비 누적 %p이고, {mmdd(t.start)} 첫 거래일을 0으로 둡니다. 세로선은 종목별 발표일, 점선은 아직 발표 전입니다. 첫 거래일 반응이 가장 강한 종목과 가장 약한 종목만 색으로 보입니다.</InfoTip>
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart margin={{ top: 24, right: 80, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis type="number" dataKey="x" domain={[lo, hi]} ticks={ticks} tickFormatter={xLabel} tick={AXIS_TICK} allowDuplicatedCategory={false} />
          <YAxis tick={AXIS_TICK} width={40} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}`} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(v) => xLabel(Number(v))} formatter={(v) => formatPp(Number(v), 1)} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" />
          {[...byDate].map(([day, tickers], k) => {
            const upcoming = !!t.end && day > t.end
            const one = tickers.length === 1 && colorOf.has(tickers[0])
            return <ReferenceLine key={day} x={toX(day)} strokeDasharray={upcoming ? "2 4" : "3 3"}
              stroke={one ? color(tickers[0]) : "var(--muted-foreground)"} strokeOpacity={upcoming ? 0.6 : 0.9}
              label={{ value: tickers.join("·"), position: "top", fontSize: 10, dy: k % 2 ? -10 : 0,
                fill: upcoming ? "var(--muted-foreground)" : "var(--foreground)" }} />
          })}
          {ordered.map(([ticker, p]) => {
            const data = p.map(([d, y]) => ({ x: toX(d), y }))
            const on = colorOf.has(ticker)
            const last = data.length ? data[data.length - 1].y : null
            return <Line key={ticker} name={ticker} data={data} dataKey="y" stroke={color(ticker)} strokeWidth={on ? 2 : 1.25} strokeOpacity={on ? 1 : 0.7} dot={false} isAnimationActive={false}
              label={(lp: { index?: number; x?: number | string; y?: number | string }) => lp.index === data.length - 1
                ? <text key={ticker} x={Number(lp.x) + 6} y={labelY(ticker, Number(lp.y) + 4)} fontSize={11} fontWeight={on ? 600 : 400} fill={on ? color(ticker) : "var(--muted-foreground)"}>{ticker} {last == null ? "" : `${last > 0 ? "+" : ""}${last.toFixed(1)}`}</text>
                : <g key={`${ticker}-${lp.index}`} />} />
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/** 시즌 하나 = 작은 가로 막대 차트 하나 (같은 눈금 ±20%p) */
function SeasonBars({ h }: { h: SectorDetail["history"][number] }) {
  const rows = h.rows.map((r) => ({ ticker: r.ticker, raw: r.d1, v: r.d1 == null ? 0 : Math.max(-20, Math.min(20, r.d1)) }))
  return (
    <div className="min-w-0">
      <p className="text-caption font-semibold">{h.label}{h.verdict && <span className="font-normal text-muted-foreground"> · {h.verdict}</span>}</p>
      <ResponsiveContainer width="100%" height={rows.length * 24 + 16}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 40 }}>
          <XAxis type="number" domain={[-20, 20]} hide />
          <YAxis type="category" dataKey="ticker" tick={AXIS_TICK} width={48} axisLine={false} tickLine={false} />
          <ReferenceLine x={0} stroke="var(--muted-foreground)" />
          <Bar dataKey="v" barSize={12} radius={2} isAnimationActive={false}>
            {rows.map((r) => <Cell key={r.ticker} fill={r.v < 0 ? "var(--color-down)" : "var(--color-up)"} />)}
            <LabelList dataKey="raw" position="right" fontSize={10.5} fill="var(--muted-foreground)"
              formatter={(v) => (v == null ? "-" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(1)}`)} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {h.one_line && <Meta>{h.one_line}</Meta>}
    </div>
  )
}

function Companies({ companies }: { companies: SectorDetail["companies"] }) {
  return (
    <Section title="종목별" note={`${companies.length}개`}>
      {companies.length === 0 ? <Meta>소속 종목이 없습니다.</Meta> : (
        <div className="flex flex-col">
          {companies.map((c) => (
            <div key={c.ticker} className="grid grid-cols-[60px_1fr_auto] items-baseline gap-x-3 border-t py-2.5 first:border-t-0">
              <Link to={`/us/${c.ticker}`} className="font-semibold hover:underline" title={c.name ? `${c.name} — 회사 상세` : "회사 상세"}>{c.ticker}</Link>
              <div className="min-w-0 space-y-0.5">
                {c.status === "reported" ? <>
                  <p className="text-caption text-muted-foreground">
                    {c.event_date && `${mmdd(c.event_date)} · `}첫 거래일 <Pp v={c.d1} />{c.d7 != null && <> → 일주일 <Pp v={c.d7} /></>}
                  </p>
                  {c.headline && <p className="text-sm">{c.headline}</p>}
                </> : <p className="text-caption text-muted-foreground">
                  {c.status === "upcoming" ? `${c.event_date ? mmdd(c.event_date) : "-"} 발표 예정` : "이번 시즌 일정 없음"}
                </p>}
                <CoreBadge core={c.core} />
              </div>
              {c.status === "reported" && c.transcript_id
                ? c.reaction
                  ? <Link to={`/follow/transcripts?t=${c.transcript_id}`} className="text-sm font-semibold text-primary hover:underline">콜 상세 →</Link>
                  : <MakeReaction transcriptId={c.transcript_id} ticker={c.ticker} />
                : c.status === "reported" ? <span className="text-caption text-muted-foreground">녹취록 대기</span> : <span />}
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}

/** 반응 정리 만들기(~1분) — 끝나면 시즌·섹터·체인 쿼리가 무효화된다 */
function MakeReaction({ transcriptId, ticker }: { transcriptId: number; ticker: string }) {
  const m = useComputeCallReaction(transcriptId)
  return (
    <Button variant="ghost" size="xs" disabled={m.isPending} title="발표일~7일 자료로 시장 반응을 정리합니다(1분 내외)"
      onClick={() => m.mutate(undefined, { onSuccess: () => toast.success(`${ticker} 시장 반응을 정리했습니다`), onError: (e) => toast.error(e.message) })}>
      {m.isPending && <Spinner className="size-3" />} 정리 만들기
    </Button>
  )
}
