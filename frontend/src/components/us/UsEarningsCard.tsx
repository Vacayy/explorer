// 도시에 '실적 발표' 카드 — 최근 실적의 시장 반응·왜 그랬나·분기별 반응을 한 장에 (docs/specs/earnings-season.md §콜 상세)
// 콜 상세(/follow/transcripts?t=)·섹터 상세로 이어진다. 데이터는 실적 시즌 체인(GET /chain/{id})을 그대로 쓴다.
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { QueryState } from "@/components/shared/QueryState"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Bullets, H3, Meta, Pp } from "@/components/follow/season/seasonUi"
import { useChain, useComputeCallReaction } from "@/hooks/useTranscripts"
import type { ChainDetail } from "@/types"

const stripCites = (s: string) => s.replace(/\s*\[\d+\](\[\d+\])*/g, "")

export function UsEarningsCard({ transcriptId }: { transcriptId: number }) {
  const q = useChain(transcriptId)
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <QueryState query={q} isEmpty={() => false} loading={<Skeleton className="h-28 w-full rounded-lg" />}>
          {(c) => <Body c={c} transcriptId={transcriptId} />}
        </QueryState>
      </CardContent>
    </Card>
  )
}

function Body({ c, transcriptId }: { c: ChainDetail; transcriptId: number }) {
  const m = c.reaction_meta
  const cur = c.history.find((h) => h.transcript_id === transcriptId) ?? c.history[0]
  const past = c.history.filter((h) => h.d1 != null).slice(0, 5)
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
    {m?.headline ? <p className="font-semibold">{stripCites(m.headline)}</p> : <NoReaction transcriptId={transcriptId} />}
    {m && (m.welcomed?.length || m.questioned?.length) ? (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {!!m.welcomed?.length && <div><H3>시장이 반긴 것</H3><Bullets items={m.welcomed.map(stripCites)} /></div>}
        {!!m.questioned?.length && <div><H3>시장이 문제 삼은 것</H3><Bullets items={m.questioned.map(stripCites)} /></div>}
      </div>
    ) : null}
    {!!c.expectation?.points?.length && <div><H3>발표 전 시장이 본 것</H3><Bullets items={[stripCites(c.expectation.points[0])]} /></div>}
    {!!m?.vs_prev?.length && <div><H3>지난 분기와 비교</H3><Bullets items={[stripCites(m.vs_prev[0])]} /></div>}
    {past.length > 1 && (
      <Meta>최근 분기 첫 거래일 반응 · {past.map((h, i) => <span key={h.event_date}>{i > 0 && " · "}{h.fiscal.replace("FY", "")} <Pp v={h.d1} /></span>)}</Meta>
    )}
  </>
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
