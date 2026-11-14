import { Link } from 'react-router-dom'
import { toApiError } from '@/api/query'
import { Band } from '@/components/home/MarketFrame'
import { Head, IndexCard, RsCard } from '@/components/industry/UsSectorPage'
import { usSectorPath } from '@/components/industry/sectorParts'
import { ErrorState } from '@/components/shared/ErrorState'
import { PageContainer } from '@/components/shared/PageContainer'
import { Skeleton } from '@/components/ui/skeleton'
import { useUsSectorMarket } from '@/hooks/useSectorView'

/** Shares the price UI only. No personal detail query or private tabs mount. */
export function PublicUsSectorPage({ ticker }: { ticker: string }) {
  const q = useUsSectorMarket(ticker.toUpperCase())
  const d = q.data
  const missing = q.isError && toApiError(q.error).status === 404
  return <PageContainer>
    <nav aria-label="위치" className="text-sm text-ink-3">
      <Link to="/industry?market=us">섹터 지도 · 미국</Link>
      {d?.parent && <> › <Link to={usSectorPath(d.parent)}>{d.parent_name}</Link></>}
      {' › '}{d?.name ?? ticker.toUpperCase()}
    </nav>
    {d ? <Head d={d} /> : <><h1 className="text-xl font-medium">{ticker.toUpperCase()}</h1>
      {!q.isError && <Skeleton className="h-8 w-full" />}</>}
    {missing ? <p role="status">없는 미국 섹터입니다. 위 링크에서 미국 섹터 지도로 돌아갈 수 있어요.</p>
      : q.isError && !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      : <Band label="대표지수와 상대강도" cells={[[8, <IndexCard key="index" q={q} />], [4, <RsCard key="rs" q={q} />]]} />}
  </PageContainer>
}
