import { Link, useParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { followEntity, unfollowEntity } from "@/api/spine"
import { tone } from "@/components/home/blockState"
import { ErrorState } from "@/components/shared/ErrorState"
import { PageLayout } from "@/components/shared/PageLayout"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { BenchmarkLabel, Chip, benchmarkValue, zoneMove } from "@/components/industry/sectorParts"
import SectorOverview from "@/components/industry/SectorOverview"
import SectorPeersTab from "@/components/industry/SectorPeersTab"
import { SectorDataTab, SectorStocksTab } from "@/components/industry/SectorTabs"
import { useFollowedEntities, useSectorDetail } from "@/hooks/useSectorView"
import { useUrlParam } from "@/hooks/useUrlParam"
import { attachToAi } from "@/lib/aiPanel"
import { toApiError } from "@/api/query"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber, formatPercent } from "@/utils/format"
import type { IndustrySectorDetail } from "@/types"

const TABS = ["overview", "peers", "data", "stocks"] as const
type Tab = (typeof TABS)[number]
const mmdd = (d: string | null | undefined) => d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : "-"

/**
 * 산업 › 섹터 화면 (/industry/:sector, ia-redesign §4.35, 시안 Sector-Overview·Sector-Peers, D-327).
 * 위치 '섹터 지도 › 섹터' → 머리(이름 · 대표지수 ETF 이름·코드 ⓘ · 값 · 1일 · 1개월 · 종목 수 · 시총 · 기준일 · RS 배지 · 팔로우 · AI에게 묻기)
 * → 탭 개요 · Peer 그룹(n) · 이 산업의 데이터(n) · 종목(n). 탭은 URL ?tab=, Peer 탭 상태는 group·view·stock·days·q.
 */
export default function SectorPage() {
  const { sector = "" } = useParams()
  const [rawTab, setTab] = useUrlParam("tab", "overview")
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? rawTab as Tab : "overview"
  const q = useSectorDetail(sector)
  const d = q.data
  const notFound = q.isError && toApiError(q.error).status === 404
  return <PageLayout mode="document">
    <div className="flex flex-col gap-2.5">
      <nav aria-label="위치" className="text-[12.5px] text-ink-3"><Link to="/industry" className="text-ink-2 hover:text-ink">섹터 지도</Link> › {sector}</nav>
      {d ? <SectorHead d={d} /> : <div className="flex min-h-[44px] flex-wrap items-end gap-4">
        <h1 className="font-display text-page font-normal tracking-[-0.01em] max-md:text-[26px]">{sector}</h1>
        {!q.isError && <><Skeleton className="h-6 w-40" /><Skeleton className="h-6 w-56" /></>}
      </div>}
      <Tabs value={tab} onValueChange={setTab} className="min-w-0">
        <div className="-mx-1 overflow-x-auto border-b px-1 [scrollbar-width:none]">
          <TabsList variant="line" aria-label="섹터 탭" className="h-10 gap-[18px] p-0">
            {([["overview", "개요", null], ["peers", "Peer 그룹", d?.peer_groups], ["data", "이 산업의 데이터", d?.data_links.length], ["stocks", "종목", d?.stocks]] as const).map(([k, label, n]) =>
              <TabsTrigger key={k} value={k} className="h-10 flex-none px-0.5 text-sm data-active:font-semibold">{label}{n != null && <span className="font-mono text-[11.5px] font-normal text-ink-3">{formatNumber(n)}</span>}</TabsTrigger>)}
          </TabsList>
        </div>
      </Tabs>
    </div>
    <div className="mt-4">
      {notFound ? <div role="status" className="space-y-2 border p-6 text-sm"><p>없는 섹터입니다.</p><Link to="/industry" className="font-semibold hover:underline">섹터 지도로 가기 ›</Link></div>
        : q.isError ? <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        : tab === "peers" ? <SectorPeersTab sector={sector} />
        : tab === "data" ? <SectorDataTab q={q} />
        : tab === "stocks" ? <SectorStocksTab q={q} />
        : <SectorOverview q={q} />}
    </div>
  </PageLayout>
}

function SectorHead({ d }: { d: IndustrySectorDetail }) {
  const qc = useQueryClient()
  const follows = useFollowedEntities()
  const followed = d.entity_id != null && !!follows.data?.some(f => f.entity_id === d.entity_id)
  const toggle = useMutation({
    mutationFn: () => followed ? unfollowEntity(d.entity_id!) : followEntity({ entity_id: d.entity_id! }),
    onSuccess: () => { toast.success(followed ? `'${d.name}' 팔로우 해제` : `'${d.name}' 팔로우`); void qc.invalidateQueries({ queryKey: ["spine", "follows"] }) },
    onError: () => toast.error("팔로우를 바꾸지 못했습니다."),
  })
  const move = zoneMove(d)
  return <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
    <h1 className="font-display text-page leading-[1.2] font-normal tracking-[-0.01em] max-md:text-[26px]">{d.name}</h1>
    <BenchmarkLabel b={d.benchmark} className="self-center pt-2" />
    <span className="font-display text-[22px] tabular-nums">{benchmarkValue(d.benchmark, d.last)}</span>
    <span className="font-mono text-sm tabular-nums"><span className={tone(d.chg_1d)}>{formatPercent(d.chg_1d, 2)}</span> <span className="text-ink-3">·</span> <span className={tone(d.ret_1m)}>1개월 {formatPercent(d.ret_1m)}</span></span>
    <span className="text-[12.5px] text-ink-3">{formatNumber(d.stocks)}종목 · 시총 {formatKrw(d.market_cap)} · {mmdd(d.as_of)}</span>
    <span className="flex flex-wrap gap-1.5">
      <Chip kind="up">장기 RS {d.rs_long == null ? "-" : Math.round(d.rs_long)}</Chip>
      <Chip kind="down">단기 RS {d.rs_short == null ? "-" : Math.round(d.rs_short)}</Chip>
      {move && <Chip kind={move.includes("→") ? "warn" : "chip"}>{move}</Chip>}
    </span>
    <span className="ml-auto flex gap-1.5 max-md:ml-0">
      {d.entity_id != null && <Button variant="outline" size="sm" className={cn("h-8 rounded-full px-3 text-[13px]", followed && "bg-chip")} aria-pressed={followed}
        disabled={toggle.isPending || follows.isPending} onClick={() => toggle.mutate()}>{followed ? "팔로우 중" : "팔로우"}</Button>}
      {d.entity_id != null && <Button variant="secondary" size="sm" className="h-8 rounded-full px-3 text-[13px]"
        onClick={() => attachToAi({ kind: "theme", ref: String(d.entity_id), label: d.name, sub: "업종", available: true })}>AI에게 묻기</Button>}
    </span>
  </div>
}
