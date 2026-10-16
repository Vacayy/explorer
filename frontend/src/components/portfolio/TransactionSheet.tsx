import { History, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import { useDeletePortfolioTransaction, usePortfolioTransactions } from '@/hooks/usePortfolio'
import { formatNumber } from '@/utils/format'
import type { PortfolioTxKind } from '@/types'
import { useState } from 'react'

const LABEL: Record<PortfolioTxKind, string> = { buy: '매수', sell: '매도', deposit: '입금', withdraw: '출금' }

/** 거래 내역 — 금액·수량 없이 날짜·유형·종목·체결가만(D-212). */
export function TransactionSheet() {
  const [open, setOpen] = useState(false)
  const list = usePortfolioTransactions(open)
  const remove = useDeletePortfolioTransaction()
  return <Sheet open={open} onOpenChange={setOpen}>
    <SheetTrigger asChild><Button size="sm" variant="outline"><History aria-hidden="true" />거래 내역</Button></SheetTrigger>
    <SheetContent className="w-full overflow-y-auto sm:max-w-md">
      <SheetHeader>
        <SheetTitle>거래 내역</SheetTitle>
        <SheetDescription>금액은 표시하지 않습니다. 잘못 입력한 거래는 삭제 후 다시 입력하세요.</SheetDescription>
      </SheetHeader>
      <div className="px-4 pb-4">
        {list.isPending ? <Skeleton className="h-40 w-full" />
          : list.isError ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
          : !list.data.length ? <EmptyState message="기록된 거래가 없습니다." />
          : <ul className="divide-y">{list.data.map(tx => <li key={tx.id} className="flex items-center gap-3 py-2.5 text-sm">
              <span className="w-20 shrink-0 tabular-nums text-muted-foreground">{tx.trade_date.slice(2)}</span>
              <span className="w-9 shrink-0 font-medium">{LABEL[tx.kind]}</span>
              <span className="min-w-0 flex-1 truncate">{tx.name ?? '현금'}{tx.price != null && <span className="ml-1.5 text-caption tabular-nums text-muted-foreground">@{formatNumber(tx.price)}</span>}</span>
              <Button size="icon-sm" variant="ghost" aria-label={`${tx.trade_date} ${LABEL[tx.kind]} 삭제`} disabled={remove.isPending}
                onClick={() => remove.mutate(tx.id, { onSuccess: () => toast.success('거래를 삭제했습니다.'), onError: e => toast.error(e.message) })}>
                <Trash2 aria-hidden="true" /></Button>
            </li>)}</ul>}
      </div>
    </SheetContent>
  </Sheet>
}
