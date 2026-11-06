// 도시에 '실적 발표' 카드 — 최근 실적의 시장 반응·왜 그랬나·분기별 반응을 한 장에 (docs/specs/earnings-season.md §콜 상세)
// 콜 상세(/follow/transcripts?t=)·섹터 상세로 이어진다. 데이터는 실적 시즌 체인(GET /chain/{id})을 그대로 쓴다.
import { Link } from "react-router-dom"
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { toast } from "sonner"
import { QueryState } from "@/components/shared/QueryState"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Bullets, DqHead, DqValue, H3, Pp } from "@/components/follow/season/seasonUi"
import { formatPp } from "@/utils/format"
import { useChain, useComputeCallReaction } from "@/hooks/useTranscripts"
import type { ChainDetail } from "@/types"

const stripCites = (s: string) => s.replace(/\s*\[\d+\](\[\d+\])*/g, "")

export function UsEarningsCard({ transcriptId }: { transcriptId: number }) {
  const q = useChain(transcriptId)
  return (
    <Card>
      <CardContent className="space-y-3 py-3">
        <QueryState query={q} isEmpty={() => false} loading={<Skeleton className="h-28 w-full rounded-card" />}>
          {(c) => <Body c={c} transcriptId={transcriptId} />}
        </QueryState>
      </CardContent>
    </Card>
  )
}

function Body({ c, transcriptId }: { c: ChainDetail; transcriptId: number }) {
  const m = c.reaction_meta
  const cur = c.history.find((h) => h.transcript_id === transcriptId) ?? c.history[0]
  const past = c.history.filter((h) => h.d1 != null).slice(0, 4)
  return <>
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-semibold">실적 발표 <span className="text-caption font-normal text-muted-foreground">{cur ? `${cur.fiscal} · ${cur.event_date}` : c.event_date}</span></h2>
      <div className="flex flex-wrap gap-3 text-sm">
        <Link to={`/follow/transcripts?t=${transcriptId}`} className="font-semibold text-primary hover:underline">콜 상세 →</Link>
        <Link to={`/follow/transcripts?view=season&sector=${encodeURIComponent(c.sector)}`} className="text-primary hover:underline">{c.sector_name} 섹터 →</Link>
      </div>
    </div>
    {cur && cur.d1 != null && (
      <p className="text-sm">
        {c.etf} 대비 첫 거래일 <Pp v={cur.d1} />
        {cur.d7 != null && <> → 일주일 <Pp v={cur.d7} /></>}
        {cur.d30 != null && <> → 한 달 <Pp v={cur.d30} /></>}
        {cur.follow && <span className="text-muted-foreground"> · 첫 반응 {cur.follow}</span>}
        {c.pt_after && c.pt_after.n > 0 && <span className="text-muted-foreground"> · 발표 후 7일 목표가 올림 {c.pt_after.up}·내림 {c.pt_after.down}</span>}
      </p>
    )}
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <ExcessChart c={c} />
      <div className="min-w-0 space-y-2">
        <H3>왜 이렇게 반응했나</H3>
        {m?.headline ? <p className="font-semibold">{stripCites(m.headline)}</p> : <NoReaction transcriptId={transcriptId} />}
      </div>
    </div>
    {m && (m.welcomed?.length || m.questioned?.length) ? (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {!!m.welcomed?.length && <div><H3>시장이 반긴 것</H3><Bullets items={m.welcomed.map(stripCites)} /></div>}
        {!!m.questioned?.length && <div><H3>시장이 문제 삼은 것</H3><Bullets items={m.questioned.map(stripCites)} /></div>}
      </div>
    ) : null}
    {!!c.expectation?.points?.length && <div><H3>발표 전 시장이 본 것</H3><Bullets items={[stripCites(c.expectation.points[0])]} /></div>}
    {!!m?.vs_prev?.length && <div><H3>지난 분기와 비교</H3><Bullets items={[stripCites(m.vs_prev[0])]} /></div>}
    {past.length > 1 && <section aria-label="최근 분기 첫 거래일 반응" className="space-y-1.5">
      <H3>최근 분기 첫 거래일 반응</H3>
      <ul className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {past.map((h) => <li key={h.event_date} className="border px-3 py-2 text-sm">
          <p className="text-caption text-muted-foreground">{h.fiscal.replace("FY", "")} · {h.event_date.slice(2).replaceAll("-", ".")}</p>
          <p className="font-mono"><Pp v={h.d1} /></p>
          <p className="text-caption text-muted-foreground">일주일 <Pp v={h.d7} />{h.follow && ` · ${h.follow}`}</p>
        </li>)}
      </ul>
    </section>}
  </>
}

/** 발표 전후 업종 ETF 대비 누적 초과수익(발표 전 마지막 거래일 = 0) */
function ExcessChart({ c }: { c: ChainDetail }) {
  const data = c.series.map((p) => ({ offset: p.offset, excess: p.excess }))
  if (data.length < 3) return <p className="text-sm text-muted-foreground">발표 전후 시세가 아직 없습니다.</p>
  return (
    <figure className="min-w-0 space-y-1" aria-label={`발표 전후 ${c.etf} 대비 누적 초과수익`}>
      <figcaption className="text-caption font-medium text-muted-foreground">발표 전후 {c.etf} 대비 누적 초과수익</figcaption>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="offset" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 11 }} tickFormatter={(v: number) => (v === 0 ? "D0" : v > 0 ? `D+${v}` : `D${v}`)} />
          <YAxis tick={{ fontSize: 11 }} width={44} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
          <Tooltip formatter={(v) => formatPp(Number(v), 1)} labelFormatter={(v) => `D${Number(v) >= 0 ? "+" : ""}${v}`} />
          <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeDasharray="3 3" />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" />
          <Line dataKey="excess" stroke="var(--foreground)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  )
}

/** 실적·사업 탭 '실적 발표 이력' — 분기별 업종 ETF 대비 첫 거래일·일주일 반응, 콜 상세 */
export function UsEarningsHistory({ transcriptId }: { transcriptId: number }) {
  const q = useChain(transcriptId)
  return (
    <Card className="gap-0 py-0" aria-label="실적 발표 이력">
      <QueryState query={q} isEmpty={(c) => c.history.length === 0} emptyMessage="실적 발표 이력이 없습니다." loading={<Skeleton className="m-4 h-28 rounded-card" />}>
        {(c) => <>
          <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-3">
            <h2 className="text-section font-semibold">실적 발표 이력</h2>
            <span className="text-caption text-muted-foreground">{c.etf} 대비 반응</span>
            <span className="ml-auto" />
            <Link to={`/follow/transcripts?view=season&sector=${encodeURIComponent(c.sector)}`} className="text-xs text-muted-foreground hover:text-foreground">{c.sector_name} 섹터 ›</Link>
          </header>
          <div className="px-4 py-2">
            <Table>
              <TableHeader><TableRow>
                <TableHead>분기</TableHead><TableHead>발표일</TableHead>
                <TableHead className="text-right">첫 거래일</TableHead><TableHead className="text-right">일주일</TableHead>
                <TableHead className="text-right"><DqHead etf={c.etf} /></TableHead>
                <TableHead className="hidden sm:table-cell">첫 반응</TableHead><TableHead className="text-right"><span className="sr-only">콜 상세</span></TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {c.history.map((h) => <TableRow key={h.event_date}>
                  <TableCell>{h.fiscal}</TableCell>
                  <TableCell className="font-mono tabular-nums">{h.event_date}</TableCell>
                  <TableCell className="text-right font-mono"><Pp v={h.d1} /></TableCell>
                  <TableCell className="text-right font-mono"><Pp v={h.d7} /></TableCell>
                  <TableCell className="text-right font-mono"><DqValue v={h.dq} partial={h.dq_partial} /></TableCell>
                  <TableCell className="hidden sm:table-cell">{h.follow ?? "-"}</TableCell>
                  <TableCell className="text-right">{h.transcript_id ? <Link to={`/follow/transcripts?t=${h.transcript_id}`} className="text-xs text-muted-foreground hover:text-foreground">콜 상세 ›</Link> : "-"}</TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </div>
        </>}
      </QueryState>
    </Card>
  )
}

function NoReaction({ transcriptId }: { transcriptId: number }) {
  const m = useComputeCallReaction(transcriptId)
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      왜 이렇게 반응했는지는 반응 정리가 있어야 볼 수 있습니다.
      <Button variant="outline" size="xs" disabled={m.isPending} title="발표일~7일 자료로 시장 반응을 정리합니다(1분 내외)"
        onClick={() => m.mutate(undefined, { onError: (e) => toast.error(e.message), onSuccess: () => toast.success("시장 반응을 정리했습니다") })}>
        {m.isPending && <Spinner className="size-3" />} 반응 정리 만들기
      </Button>
    </div>
  )
}
