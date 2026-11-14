import { Link } from "react-router-dom"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { FillNote, FillSkeleton, MarketCard } from "@/components/home/MarketFrame"
import { FillArea } from "@/components/shared/Bounded"
import { DataLinkCard } from "@/components/industry/SectorOverview"
import { PagerBar, paged } from "@/components/shared/PagerBar"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useUrlParam } from "@/hooks/useUrlParam"
import { cn } from "@/lib/utils"
import { formatKrw, formatPercent } from "@/utils/format"
import type { useSectorDetail } from "@/hooks/useSectorView"

type Q = ReturnType<typeof useSectorDetail>
const PER = 20

/** 섹터 화면 › 이 산업의 데이터 — 연결된 모니터링 화면의 이 섹터 몫을 카드 벽으로(§4.8a 방식). 누르면 그 화면을 이 섹터 쪽으로 연다 */
export function SectorDataTab({ q }: { q: Q }) {
  const cards = q.data?.data_links ?? []
  return <section aria-label="이 산업의 데이터" className="flex flex-col gap-3 border bg-card px-[18px] py-4">
    <BlockHead section title="이 산업의 데이터" info="수출입 품목 · 대만 공급망 계층 · 밸류체인 칸 · 미국 실적 시즌 · 회사채 묶음 중 이 섹터와 이어진 것만 보입니다."
      sub={q.data ? `연결 ${cards.length}` : " "} />
    {q.isError ? <BlockError message="연결 데이터를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !q.data ? <div className="grid grid-cols-1 pr-px pb-px sm:grid-cols-2 lg:grid-cols-3 [&>*]:-mr-px [&>*]:-mb-px">{[0, 1, 2].map(i => <Skeleton key={i} className="h-[150px] rounded-none border" />)}</div>
      : !cards.length ? <p role="status" className="py-6 text-sm text-ink-3">연결된 데이터 화면이 없습니다.</p>
      : <div className="grid grid-cols-1 pr-px pb-px sm:grid-cols-2 lg:grid-cols-3 [&>*]:-mr-px [&>*]:-mb-px">{cards.map(c => <DataLinkCard key={c.kind} c={c} big />)}</div>}
  </section>
}

/** 섹터 화면 › 종목 — 구성 종목 표(시총 · 비중 · 1일 · 1개월 · RS), 20개씩(URL page) */
export function SectorStocksTab({ q }: { q: Q }) {
  const [rawPage, setPage] = useUrlParam("page", "1")
  const rows = q.data?.constituents ?? []
  const p = paged(rows, Math.max(0, (Number(rawPage) || 1) - 1), PER)
  return <MarketCard band="sectorPeers" label="sector.stocks">
    <BlockHead section title="구성 종목" info="이 섹터로 분류된 종목입니다(업종 정정 반영). 비중은 섹터 시가총액 대비, RS는 전 종목 대비 백분위(장기 3개월 · 단기 1주)입니다."
      sub={q.data ? `시총 순 · ${q.data.as_of ? `${+q.data.as_of.slice(5, 7)}/${+q.data.as_of.slice(8, 10)}` : ""}` : " "} />
    {q.isError ? <BlockError message="구성 종목을 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
      : !q.data ? <FillSkeleton rows={14} />
      : !rows.length ? <FillNote>이 섹터로 분류된 종목이 없습니다.</FillNote>
      : <>
        <FillArea aria-label="구성 종목">
          <Table className="text-[13px]">
            <TableHeader><TableRow>
              <TableHead className="w-10 text-[12px]">#</TableHead><TableHead className="text-[12px]">종목</TableHead>
              <TableHead className="text-right text-[12px]">시총</TableHead><TableHead className="text-right text-[12px]">비중</TableHead>
              <TableHead className="text-right text-[12px]">1일</TableHead><TableHead className="text-right text-[12px]">1개월</TableHead>
              <TableHead className="text-right text-[12px] max-sm:hidden">장기 RS</TableHead><TableHead className="text-right text-[12px] max-sm:hidden">단기 RS</TableHead>
            </TableRow></TableHeader>
            <TableBody>{p.rows.map((c, i) => <TableRow key={c.stock_code}>
              <TableCell className="font-mono text-ink-3 tabular-nums">{p.from + i}</TableCell>
              <TableCell className="max-w-[220px] truncate"><Link to={`/analyze/${c.stock_code}/summary`} className="font-medium hover:underline">{c.corp_name}</Link></TableCell>
              <TableCell className="text-right font-mono tabular-nums">{formatKrw(c.market_cap)}</TableCell>
              <TableCell className="text-right font-mono text-ink-2 tabular-nums">{formatPercent(c.weight).replace("+", "")}</TableCell>
              <TableCell className={cn("text-right font-mono tabular-nums", tone(c.chg_1d))}>{formatPercent(c.chg_1d)}</TableCell>
              <TableCell className={cn("text-right font-mono tabular-nums", tone(c.ret_1m))}>{formatPercent(c.ret_1m)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums max-sm:hidden">{c.rs_long == null ? "-" : Math.round(c.rs_long)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums max-sm:hidden">{c.rs_short == null ? "-" : Math.round(c.rs_short)}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </FillArea>
        <PagerBar {...p} onPage={n => setPage(String(n + 1))} label="구성 종목 페이지" />
      </>}
  </MarketCard>
}
