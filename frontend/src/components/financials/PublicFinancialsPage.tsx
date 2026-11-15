import { Link, useSearchParams } from 'react-router-dom'
import { useCompany, useCompanySearch } from '@/hooks/useCompanySearch'
import { PageContainer } from '@/components/shared/PageContainer'
import { QueryState } from '@/components/shared/QueryState'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import FinancialsPage from '@/components/financials/FinancialsPage'

export function PublicFinancialSearch() {
  const [params, setParams] = useSearchParams()
  const query = useCompanySearch(params.get('q') ?? '')
  return <PageContainer>
    <h1 className="text-xl font-medium">기업 재무 조회</h1>
    <p className="text-sm text-muted-foreground">기업명이나 종목 코드로 저장된 재무 자료를 찾아보세요.</p>
    <Input aria-label="기업명 또는 종목 코드" type="search" maxLength={100} value={params.get('q') ?? ''}
      onChange={event => setParams({ q: event.target.value }, { replace: true })} />
    <QueryState query={query} emptyMessage="검색 조건에 맞는 기업이 없습니다.">
      {companies => <ul className="divide-y">{companies.map(company => <li key={company.corp_code} className="py-3">
        <Link className="underline" to={`/analyze/${company.stock_code}/financials?q=${encodeURIComponent(params.get('q') ?? '')}`}>
          {company.corp_name} · {company.stock_code}
        </Link>
      </li>)}</ul>}
    </QueryState>
    <Button variant="outline" asChild><Link to="/home/kr">한국 시장으로</Link></Button>
  </PageContainer>
}

export function PublicFinancialsPage({ stockCode }: { stockCode: string }) {
  const company = useCompany(stockCode)
  const [params] = useSearchParams()
  return <>
    <PageContainer>
      <Button variant="outline" asChild><Link to={`/financials?q=${encodeURIComponent(params.get('q') ?? '')}`}>기업 검색으로</Link></Button>
      <QueryState query={company} emptyMessage="등록되지 않은 종목입니다.">
        {value => <h1 className="text-xl font-medium">{value.corp_name} · {value.stock_code} 재무</h1>}
      </QueryState>
    </PageContainer>
    {company.data && <FinancialsPage stockCode={stockCode} publicView />}
  </>
}
