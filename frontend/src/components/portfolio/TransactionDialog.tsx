import { useState } from 'react'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import SegmentTabs from '@/components/shared/SegmentTabs'
import CompanySearchCombobox from '@/components/shared/CompanySearchCombobox'
import { useAddPortfolioTransaction } from '@/hooks/usePortfolio'
import type { Company, PortfolioTxKind } from '@/types'

const KINDS: { value: PortfolioTxKind; label: string }[] = [
  { value: 'buy', label: '매수' }, { value: 'sell', label: '매도' },
  { value: 'deposit', label: '입금' }, { value: 'withdraw', label: '출금' },
]
const today = () => new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10)   // KST

/** 거래 입력 — 금액은 여기서만 입력하고 저장 후 지운다. 화면 어디에도 다시 표시하지 않는다(D-212). */
export function TransactionDialog() {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<PortfolioTxKind>('buy')
  const [company, setCompany] = useState<Pick<Company, 'corp_name' | 'stock_code'> | null>(null)
  const [date, setDate] = useState(today)
  const [amount, setAmount] = useState('')
  const [price, setPrice] = useState('')
  const [fund, setFund] = useState(true)
  const add = useAddPortfolioTransaction()
  const trade = kind === 'buy' || kind === 'sell'
  const manwon = Number(amount.replaceAll(',', ''))
  const valid = manwon > 0 && /^\d{4}-\d{2}-\d{2}$/.test(date) && (!trade || !!company) && (!price || Number(price.replaceAll(',', '')) > 0)
  const reset = () => { setAmount(''); setPrice(''); setCompany(null); setKind('buy'); setDate(today()); setFund(true); add.reset() }

  const submit = () => add.mutate({
    trade_date: date, kind, amount: manwon * 10_000,
    ...(trade && company?.stock_code ? { stock_code: company.stock_code } : {}),
    ...(trade && price ? { price: Number(price.replaceAll(',', '')) } : {}),
    ...(kind === 'buy' ? { fund_shortfall: fund } : {}),
  }, {
    onSuccess: () => { toast.success('거래를 기록했습니다.'); reset(); setOpen(false) },
  })

  return <Dialog open={open} onOpenChange={value => { setOpen(value); if (!value) reset() }}>
    <DialogTrigger asChild><Button size="sm"><Plus aria-hidden="true" />거래 입력</Button></DialogTrigger>
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>거래 입력</DialogTitle>
        <DialogDescription>금액은 로컬에만 저장되고 화면에는 비율로만 표시됩니다.</DialogDescription>
      </DialogHeader>
      <form className="space-y-4" onSubmit={event => { event.preventDefault(); if (valid && !add.isPending) submit() }}>
        <SegmentTabs tabs={KINDS} value={kind} onChange={value => setKind(value as PortfolioTxKind)} />
        {trade && <div className="space-y-1.5"><Label>종목</Label><CompanySearchCombobox value={company} onSelect={setCompany} className="w-full" /></div>}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5"><Label htmlFor="pf-date">날짜</Label><Input id="pf-date" type="date" value={date} onChange={e => setDate(e.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="pf-amount">{kind === 'buy' ? '매수 금액' : kind === 'sell' ? '매도 금액' : kind === 'deposit' ? '입금액' : '출금액'} (만원)</Label>
            <Input id="pf-amount" inputMode="decimal" autoComplete="off" value={amount} onChange={e => setAmount(e.target.value)} placeholder="예: 100" /></div>
        </div>
        {trade && <div className="space-y-1.5"><Label htmlFor="pf-price">체결가 (원, 비우면 그날 종가)</Label>
          <Input id="pf-price" inputMode="decimal" autoComplete="off" value={price} onChange={e => setPrice(e.target.value)} placeholder="최근 저장 종가" /></div>}
        {kind === 'buy' && <div className="flex items-center gap-2"><Checkbox id="pf-fund" checked={fund} onCheckedChange={value => setFund(value === true)} />
          <Label htmlFor="pf-fund" className="font-normal">현금이 부족하면 부족분을 입금으로 기록</Label></div>}
        {add.error && <p role="alert" className="text-sm text-destructive">{add.error.message}</p>}
        <DialogFooter><Button type="submit" disabled={!valid || add.isPending}>{add.isPending ? '기록 중…' : '기록'}</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
}
