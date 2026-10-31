// 섹터 상세 (?view=season&sector=<키>[&season=]) — 시즌 → 섹터 → 콜 3단의 가운데 (docs/specs/earnings-season.md §섹터 상세)
import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { QueryState } from "@/components/shared/QueryState"
import { useComputeCallReaction, useSeasonSector } from "@/hooks/useTranscripts"
import { formatPp } from "@/utils/format"
import { Bullets, Cols, CoreBadge, Meta, Pp, Section, VerdictBadge, mmdd, seasonLabel } from "@/components/follow/season/seasonUi"
import type { SectorDetail } from "@/types"

/** 종목별 선 색 — 테마 차트 토큰만 */
const LINE_COLORS = ["var(--color-chart-1)", "var(--color-chart-3)", "var(--color-chart-4)", "var(--color-chart-2)",
  "var(--color-chart-5)", "var(--color-chart-red)", "var(--color-chart-gray)", "var(--color-chart-yellow)"]
const TOOLTIP_STYLE = { fontSize: 12, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" }
const dLabel = (v: number) => (v === 0 ? "D" : v > 0 ? `D+${v}` : `D${v}`)

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
      loading={<div className="space-y-4">{crumb()}<Skeleton className="h-72 w-full rounded-xl" /><Skeleton className="h-48 w-full rounded-xl" /></div>}>
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
        <PathChart paths={d.paths} etf={d.etf} />
      </Section>

      <Cols>
        <Section title="시장이 반긴 것 / 문제 삼은 것">
          {body && (body.welcomed?.length || body.questioned?.length) ? <>
            {!!body.welcomed?.length && <><h3 className="text-sm font-semibold">반긴 것</h3><Bullets items={body.welcomed} /></>}
            {!!body.questioned?.length && <><h3 className="mt-2 text-sm font-semibold">문제 삼은 것</h3><Bullets items={body.questioned} /></>}
          </> : <Meta>섹터 요약이 아직 없습니다. 반응 정리가 2건 이상이면 매일 07:20에 만들어집니다.</Meta>}
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
        <Section title="지난 시즌과 비교">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
            {d.history.map((h) => <SeasonBars key={h.season} h={h} />)}
          </div>
          <Meta>시즌별 발표 후 첫 거래일 {d.etf} 대비 %p(같은 눈금 ±20). 시즌 = 발표 시점 기준.</Meta>
          {!!body?.vs_last_season?.length && <Bullets items={body.vs_last_season} />}
        </Section>
      )}
    </div>
  )
}

/** 발표일 기준으로 정렬한 반응 경로 — 발표일이 달라도 반응 모양을 나란히 */
function PathChart({ paths, etf }: { paths: SectorDetail["paths"]; etf: string }) {
  const entries = Object.entries(paths).filter(([, p]) => p.length > 0)
  if (!entries.length) return <Meta>이번 시즌 발표한 소속 종목의 시세가 아직 없습니다.</Meta>
  const maxOff = Math.max(5, ...entries.flatMap(([, p]) => p.map(([o]) => o)))
  const ticks = Array.from({ length: Math.floor((maxOff + 5) / 5) + 1 }, (_, i) => -5 + i * 5)
  return (
    <div className="space-y-1">
      <h3 className="text-sm font-semibold">발표일 기준 반응 경로</h3>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart margin={{ top: 8, right: 44, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis type="number" dataKey="x" domain={[-5, maxOff]} ticks={ticks} tickFormatter={dLabel} tick={AXIS_TICK} allowDuplicatedCategory={false} />
          <YAxis tick={AXIS_TICK} width={40} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}`} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(v) => dLabel(Number(v))} formatter={(v) => formatPp(Number(v), 1)} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" />
          <ReferenceLine x={0} stroke="var(--primary)" strokeDasharray="3 3" label={{ value: "발표일", position: "insideTopRight", fontSize: 11, fill: "var(--foreground)" }} />
          {entries.map(([ticker, p], i) => {
            const color = LINE_COLORS[i % LINE_COLORS.length]
            const data = p.map(([x, y]) => ({ x, y }))
            return <Line key={ticker} name={ticker} data={data} dataKey="y" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false}
              label={(lp: { index?: number; x?: number | string; y?: number | string }) => lp.index === data.length - 1
                ? <text key={ticker} x={Number(lp.x) + 6} y={Number(lp.y) + 4} fontSize={11} fontWeight={600} fill={color}>{ticker}</text>
                : <g key={`${ticker}-${lp.index}`} />} />
          })}
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </LineChart>
      </ResponsiveContainer>
      <Meta>{etf} 대비 누적 %p, 발표 전 마지막 거래일 = 0. 가로축은 발표일 기준 거래일.</Meta>
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
    <Section title="종목별">
      {companies.length === 0 ? <Meta>소속 종목이 없습니다.</Meta> : (
        <div className="flex flex-col">
          {companies.map((c) => (
            <div key={c.ticker} className="grid grid-cols-[60px_1fr_auto] items-baseline gap-x-3 border-t py-2.5 first:border-t-0">
              <span className="font-semibold" title={c.name ?? undefined}>{c.ticker}</span>
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
                : <span />}
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
