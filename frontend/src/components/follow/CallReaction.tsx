import { QueryState } from "@/components/shared/QueryState"
// 컨콜 시장 반응 — 발표일부터 7일 동안 내 자료·주가·Yahoo 헤드라인을 정리한 것 (핵심 정리 아래).
// 기간 중엔 버튼으로 중간 정리(interim), 7일이 지나면 매일 회차가 확정본(final)을 만든다.
import { Link } from "react-router-dom"
import { ChevronRight, Megaphone, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Markdown } from "@/components/shared/Markdown"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useCallReaction, useComputeCallReaction } from "@/hooks/useTranscripts"
import { formatPercent } from "@/utils/format"
import { cn } from "@/lib/utils"
import type { CallReaction as Reaction } from "@/types"

const WINDOW_DAYS = 7
const mmdd = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`
const addDays = (iso: string, n: number) => { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10) }
const daysSince = (iso: string) => Math.floor((Date.now() - new Date(iso + "T00:00:00").getTime()) / 86_400_000)
const tone = (v: number | null) => v == null ? "text-muted-foreground" : v > 0 ? "text-up" : v < 0 ? "text-down" : ""

export function CallReaction({ transcriptId, callDate }: { transcriptId: number; callDate: string | null }) {
  const query = useCallReaction(transcriptId)
  const compute = useComputeCallReaction(transcriptId)
  const run = () => compute.mutate(undefined, { onError: (e) => toast.error(e.message) })

  const header = (r?: Reaction | null) => (
    <div className="flex flex-wrap items-center gap-1.5 mb-1.5 text-sm font-semibold">
      <Megaphone className="h-4 w-4 text-muted-foreground" /> 시장 반응
      {callDate && (
        <span className="text-[11px] font-normal text-muted-foreground">
          {mmdd(callDate)}~{mmdd(addDays(callDate, WINDOW_DAYS))} · 내 자료·주가·헤드라인
        </span>
      )}
      {r?.status === "interim" && <Badge variant="outline" className="text-[10px]">진행 중 · 발표 {daysSince(r.window_start)}일째</Badge>}
      {r?.status === "final" && <Badge variant="secondary" className="text-[10px]">확정</Badge>}
      {r?.status === "interim" && (
        <Button variant="ghost" size="xs" className="ml-auto" onClick={run} disabled={compute.isPending}
          title="새 자료가 있으면 다시 정리합니다(없으면 그대로)">
          <RefreshCw className={cn("h-3 w-3", compute.isPending && "animate-spin")} /> 다시 정리
        </Button>
      )}
    </div>
  )

  return <QueryState query={query} loading={<section>{header()}<Skeleton className="h-16 w-full" /></section>} isEmpty={() => false}>{data => {
    if (!data) {
      const future = !callDate || callDate > new Date().toISOString().slice(0, 10)
      return (
        <section>
          {header()}
          {compute.isPending ? (
            <div className="rounded-lg bg-muted/40 px-4 py-3 space-y-2">
              <Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/6" />
              <p className="text-xs text-muted-foreground">기간 안의 자료를 모아 정리하는 중… (1분 내외)</p>
            </div>
          ) : future ? (
            <p className="text-xs text-muted-foreground">{callDate ? "아직 발표 전입니다." : "발표일을 모르는 컨콜이라 기간을 정할 수 없습니다."}</p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onClick={run}><Megaphone className="h-3.5 w-3.5" /> 시장 반응 정리 (LLM)</Button>
              <span className="text-[11px] text-muted-foreground">
                {daysSince(callDate!) > WINDOW_DAYS ? "기간이 끝난 콜은 확정본으로 저장됩니다" : "기간 중이면 중간 정리, 7일 뒤 자동으로 확정됩니다"}
              </span>
            </div>
          )}
        </section>
      )
    }

    return (
      <section className="space-y-2">
        {header(data)}
        {data.prices && <PriceStrip prices={data.prices} />}
        {data.body ? (
          <div className={cn("rounded-lg bg-muted/40 px-4 py-3", compute.isPending && "opacity-60")}><Markdown>{data.body}</Markdown></div>
        ) : (
          <p className="text-xs text-muted-foreground">기간 안에 이 회사를 다룬 내 자료·헤드라인을 찾지 못했습니다.</p>
        )}
        {data.sources.length > 0 && <Sources reaction={data} />}
      </section>
    )
  }}</QueryState>
}

function PriceStrip({ prices }: { prices: NonNullable<Reaction["prices"]> }) {
  return (
    <div className="overflow-x-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead className="h-7 text-[11px]">발표 전 종가({mmdd(prices.base_date)}) 대비</TableHead>
            {prices.days.map((d) => <TableHead key={d.date} className="h-7 text-right text-[11px] tabular-nums">{mmdd(d.date)}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell className="py-1 font-medium">종목</TableCell>
            {prices.days.map((d) => <TableCell key={d.date} className={cn("py-1 text-right tabular-nums font-medium", tone(d.ret))}>{formatPercent(d.ret)}</TableCell>)}
          </TableRow>
          <TableRow>
            <TableCell className="py-1 text-muted-foreground">SPY</TableCell>
            {prices.days.map((d) => <TableCell key={d.date} className={cn("py-1 text-right tabular-nums", tone(d.spy_ret))}>{formatPercent(d.spy_ret)}</TableCell>)}
          </TableRow>
        </TableBody>
      </Table>
    </div>
  )
}

function Sources({ reaction }: { reaction: Reaction }) {
  const cited = reaction.sources.filter((s) => s.cited).length
  return (
    <Collapsible>
      <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronRight className="h-3 w-3 transition-transform group-data-[state=open]:rotate-90" />
        출처 {reaction.sources.length}건 · 인용 {cited}건
        {reaction.n_docs > reaction.sources.filter((s) => s.kind === "doc").length && ` · 내 자료 ${reaction.n_docs}건 중 언급 많은 순`}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-1.5 space-y-0.5 text-xs">
          {reaction.sources.map((s) => (
            <li key={s.n} className={cn("flex gap-1.5", !s.cited && "opacity-60")}>
              <span className="w-6 shrink-0 text-right tabular-nums text-muted-foreground">[{s.n}]</span>
              <span className="shrink-0 text-muted-foreground">{s.kind === "headline" ? "헤드라인" : s.source}</span>
              {s.kind === "doc" && s.doc_id ? (
                <Link to={`/doc/${s.doc_id}`} className="truncate hover:underline">{s.title || "(제목 없음)"}</Link>
              ) : (
                <a href={s.url} target="_blank" rel="noreferrer" className="truncate hover:underline">{s.title}</a>
              )}
              {s.published_at && <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{mmdd(s.published_at.slice(0, 10))}</span>}
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}
