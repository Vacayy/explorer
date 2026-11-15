import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { toApiError } from '@/api/query'
import { Band } from '@/components/home/MarketFrame'
import { tone } from '@/components/home/blockState'
import { IndexCard, RsCard } from '@/components/industry/SectorOverview'
import { SectorStocksTab } from '@/components/industry/SectorTabs'
import { BenchmarkLabel, benchmarkValue } from '@/components/industry/sectorParts'
import { PageContainer } from '@/components/shared/PageContainer'
import { QueryState } from '@/components/shared/QueryState'
import { useKrSectorMarket } from '@/hooks/useSectorView'
import { formatKrw, formatNumber, formatPercent } from '@/utils/format'

/** Reuses the market presentation without mounting personal sector queries. */
export function PublicKrSectorPage({ sector }: { sector: string }) {
  const query = useKrSectorMarket(sector)
  const location = useLocation()
  const [params] = useSearchParams()
  const mapQuery = params.get('map_query') ?? ''
  const mapHref = `/industry${mapQuery.startsWith('?') ? mapQuery : ''}`
  const companyHref = (code: string) => `/analyze/${encodeURIComponent(code)}/summary?${new URLSearchParams({ sector, sector_query: location.search })}`
  const missing = query.isError && !query.data && toApiError(query.error).status === 404
  return <PageContainer>
    <nav aria-label="위치" className="text-sm text-ink-3"><Link to={mapHref}>한국 산업 지도</Link> › {sector}</nav>
    <h1 className="font-display text-page font-normal">{sector}</h1>
    {missing ? <p role="status">이 섹터의 공개 시장 자료가 없습니다. 한국 산업 지도에서 다른 섹터를 선택해 주세요.</p> :
      <QueryState query={query} emptyMessage="표시할 섹터 시장 자료가 없습니다.">{data => <>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <BenchmarkLabel b={data.benchmark} />
          <span className="font-display text-2xl tabular-nums">{benchmarkValue(data.benchmark, data.last)}</span>
          <span className={tone(data.chg_1d)}>1일 {formatPercent(data.chg_1d)}</span>
          <span className={tone(data.ret_1m)}>1개월 {formatPercent(data.ret_1m)}</span>
          <span className="text-sm text-ink-3">{formatNumber(data.stocks)}종목 · 시총 {formatKrw(data.market_cap)}</span>
        </div>
        <p className="my-3 text-sm text-ink-3">구성 종목 기준일 {data.as_of ?? '-'} · 대표지수 시세일 {data.last_date ?? '-'} · 저장 시세이며 실시간 정보가 아닙니다.</p>
        {(data.last == null || data.rs_long == null || data.rs_short == null || data.constituents.some(row => row.chg_1d == null || row.ret_1m == null)) &&
          <p role="status" className="mb-3 text-sm text-ink-3">일부 시세·상대강도 자료가 부족합니다. 확인되지 않은 수치는 -로 표시합니다.</p>}
        <Band label="대표지수와 상대강도" cells={[[8, <IndexCard key="index" q={query} />], [4, <RsCard key="rs" q={query} companyHref={companyHref} />]]} />
        <div className="mt-4"><SectorStocksTab q={query} companyHref={companyHref} /></div>
        <p className="mt-3 text-sm text-ink-3">공개 산업 해설·관련 문서·Peer 연결은 준비 중입니다.</p>
      </>}</QueryState>}
  </PageContainer>
}
