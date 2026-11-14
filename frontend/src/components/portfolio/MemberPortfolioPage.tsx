import { useMemberAccess } from '@/components/auth/MemberAccess'
import { googleLoginUrl } from '@/api/auth'
import { toApiError } from '@/api/errors'
import { PageContainer } from '@/components/shared/PageContainer'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import AreaSeriesChart from '@/components/charts/AreaSeriesChart'
import { TransactionFormDialog } from '@/components/portfolio/TransactionDialog'
import { MemberCompanyPicker } from '@/components/portfolio/MemberCompanyPicker'
import { useAddMemberPortfolioTransaction, useDeleteMemberPortfolioTransaction, useMemberPortfolio,
  useMemberPortfolioHistory, useMemberPortfolioTransactions } from '@/hooks/useMemberPortfolio'
import { formatNumber, formatPercent, formatRatio } from '@/utils/format'
import type { PortfolioTxKind } from '@/types'

const KIND: Record<PortfolioTxKind, string> = { buy: '매수', sell: '매도', deposit: '입금', withdraw: '출금' }

export function MemberPortfolioPage() {
  const access = useMemberAccess()
  if (access.status === 'loading') return <PageContainer><Skeleton className="h-40" /><span role="status">계정 확인 중…</span></PageContainer>
  if (access.status === 'error') return <PageContainer><ErrorState message="로그인 상태를 확인할 수 없습니다." onRetry={access.retry} /></PageContainer>
  if (access.status !== 'member' && access.status !== 'operator') return <PageContainer>
    <h1 className="text-xl font-medium">내 포트폴리오</h1><p>로그인하면 본인의 거래와 포트폴리오를 기록할 수 있습니다.</p>
    <Button asChild><a href={googleLoginUrl('/portfolio')}>Google 로그인</a></Button>
  </PageContainer>
  return <MemberPortfolio key={access.session!.user!.id} />
}

function MemberPortfolio() {
  const access = useMemberAccess()
  const summary = useMemberPortfolio()
  const history = useMemberPortfolioHistory()
  const transactions = useMemberPortfolioTransactions()
  const add = useAddMemberPortfolioTransaction()
  const remove = useDeleteMemberPortfolioTransaction()
  const data = summary.data
  const denied = [summary.error, history.error, transactions.error, add.error, remove.error]
    .some(error => error && [401, 403].includes(toApiError(error).status ?? 0))
  if (denied) return <PageContainer><ErrorState message="계정 접근 권한을 다시 확인해 주세요." onRetry={() => {
    access.retry(); add.reset(); remove.reset()
    void summary.refetch(); void history.refetch(); void transactions.refetch()
  }} /></PageContainer>
  return <PageContainer>
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-xl font-medium">내 포트폴리오</h1><p className="text-sm text-ink-2">비율·가격만 표시합니다.{data?.as_of ? ` ${data.as_of} 기준` : ''}</p></div>
      <TransactionFormDialog add={add} CompanyPicker={MemberCompanyPicker} description="금액은 본인의 거래 기록으로 저장됩니다. 조회 화면에는 비율과 가격만 표시됩니다." />
    </header>
    {summary.isError ? <ErrorState message="포트폴리오를 불러오지 못했습니다." onRetry={() => void summary.refetch()} />
      : summary.isPending ? <Skeleton className="h-48 w-full" />
      : data && <>
        {data.holdings.length === 0 && data.cash_weight_pct == null ? <EmptyState message="아직 기록된 거래가 없습니다. 거래 입력에서 입금 또는 매수를 기록하세요." />
          : <Card><CardContent className="grid grid-cols-2 gap-4 py-4 sm:grid-cols-4">
            {[
              ['계좌 수익률', formatPercent(data.total_return_pct)], ['현금 비중', formatRatio(data.cash_weight_pct)],
              ['실현 손익', formatPercent(data.realized_pct)], ['미실현 손익', formatPercent(data.unrealized_pct)],
            ].map(([label, value]) => <div key={label}><p className="text-sm text-ink-2">{label}</p><p className="text-xl tabular-nums">{value}</p></div>)}
          </CardContent></Card>}
        {data.holdings.length > 0 && <Card><CardHeader><CardTitle>보유 종목</CardTitle></CardHeader><CardContent>
          {data.holdings.some(h => h.last_close == null) && <p role="status" className="mb-2 text-sm text-ink-2">일부 종목의 저장된 시세가 없습니다.</p>}
          <Table><TableHeader><TableRow><TableHead>종목</TableHead><TableHead>비중</TableHead><TableHead>수익률</TableHead><TableHead>평단</TableHead><TableHead>최근 가격</TableHead></TableRow></TableHeader>
            <TableBody>{data.holdings.map(h => <TableRow key={h.code}><TableCell>{h.name}<span className="block text-xs text-ink-2">{h.code}</span></TableCell>
              <TableCell>{formatRatio(h.weight_pct)}</TableCell><TableCell>{formatPercent(h.return_pct)}</TableCell><TableCell>{formatNumber(h.avg_price)}</TableCell><TableCell>{formatNumber(h.last_close)}</TableCell>
            </TableRow>)}</TableBody></Table>
        </CardContent></Card>}
        {data.closed.length > 0 && <Card><CardHeader><CardTitle>청산 내역</CardTitle></CardHeader><CardContent>
          <Table><TableHeader><TableRow><TableHead>종목</TableHead><TableHead>매도일</TableHead><TableHead>매도가</TableHead><TableHead>수익률</TableHead></TableRow></TableHeader>
            <TableBody>{data.closed.map((h, index) => <TableRow key={`${h.code}:${h.sell_date}:${index}`}><TableCell>{h.name}</TableCell><TableCell>{h.sell_date}</TableCell><TableCell>{formatNumber(h.sell_price)}</TableCell><TableCell>{formatPercent(h.return_pct)}</TableCell></TableRow>)}</TableBody></Table>
        </CardContent></Card>}
      </>}
    <Card><CardHeader><CardTitle>수익률 추이</CardTitle></CardHeader><CardContent>
      {history.isError ? <ErrorState message="수익률 추이를 불러오지 못했습니다." onRetry={() => void history.refetch()} />
        : history.isPending ? <Skeleton className="h-40" /> : history.data.length === 0 ? <p className="text-sm text-ink-2">표시할 수익률 이력이 없습니다.</p>
        : <AreaSeriesChart data={history.data.map(p => ({ time: p.date, value: p.cum_return_pct }))} formatValue={formatPercent} height={220} />}
    </CardContent></Card>
    <Card><CardHeader><CardTitle>거래 내역</CardTitle></CardHeader><CardContent>
      <p className="mb-3 text-sm text-ink-2">잘못 입력한 거래는 삭제 후 다시 입력하세요. 금액·수량은 표시하지 않습니다.</p>
      {remove.isError && <p role="alert" className="mb-2 text-sm text-destructive">{remove.error.message}</p>}
      {transactions.isError ? <ErrorState message="거래 내역을 불러오지 못했습니다." onRetry={() => void transactions.refetch()} />
        : transactions.isPending ? <Skeleton className="h-32" />
        : transactions.data.length === 0 ? <p>기록된 거래가 없습니다.</p>
        : <ul className="divide-y">{transactions.data.map(tx => <li key={tx.id} className="flex flex-wrap items-center gap-2 py-3 text-sm">
          <span className="tabular-nums text-ink-2">{tx.trade_date}</span><span>{KIND[tx.kind]}</span><span className="min-w-0 flex-1 break-words">{tx.name ?? '현금'}</span>
          {tx.price != null && <span className="tabular-nums">@{formatNumber(tx.price)}</span>}
          <Button variant="outline" size="sm" disabled={remove.isPending} aria-label={`${tx.trade_date} ${KIND[tx.kind]} 삭제`} onClick={() => remove.mutate(tx.id)}>삭제</Button>
        </li>)}</ul>}
    </CardContent></Card>
  </PageContainer>
}
