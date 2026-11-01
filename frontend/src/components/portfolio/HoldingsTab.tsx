import { useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { HoldingDetail } from '@/components/portfolio/HoldingDetail'
import { formatNumber, formatPercent, formatRatio } from '@/utils/format'
import type { PortfolioSummary } from '@/types'

// 좁은 화면 — 금액성 열(평단·매도가)은 숨기고 셀 여백을 줄여 표가 카드 안에 들어오게
const WIDE = 'hidden md:table-cell'
const COMPACT = '[&_td]:px-2 [&_th]:px-2 md:[&_td]:px-3 md:[&_th]:px-3'
const tone = (v: number | null | undefined) => v == null || v === 0 ? '' : v > 0 ? 'text-up' : 'text-down'

/** 보유 탭 — 보유 표 · 청산 내역 · 종목 상세(?stock=, 가격·기술적 분석·논지·자료 흐름·공시·뉴스). */
export function HoldingsTab({ data }: { data: PortfolioSummary }) {
  const [sp, setSp] = useSearchParams()
  const detailRef = useRef<HTMLElement>(null)
  const selected = data.holdings.find(h => h.code === sp.get('stock')) ?? data.holdings[0]
  const select = (code: string, scroll = false) => {
    setSp(prev => { const n = new URLSearchParams(prev); n.set('stock', code); return n }, { replace: true, preventScrollReset: true })
    if (scroll) detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  return <>
    <Card><CardHeader><CardTitle>보유 종목</CardTitle></CardHeader><CardContent>
      <Table className={COMPACT}><TableHeader><TableRow>
        <TableHead>종목</TableHead><TableHead className="text-right">비중</TableHead><TableHead className={`text-right ${WIDE}`}>평단</TableHead>
        <TableHead className="text-right">현재가</TableHead><TableHead className="text-right">수익률</TableHead><TableHead className="text-right">전일비</TableHead>
      </TableRow></TableHeader><TableBody>
        {data.holdings.map(h => <TableRow key={h.code} className="cursor-pointer" data-state={h.code === selected?.code ? 'selected' : undefined} onClick={() => select(h.code, true)}>
          <TableCell className="font-medium">{h.name}</TableCell>
          <TableCell className="text-right tabular-nums">{formatRatio(h.weight_pct)}</TableCell>
          <TableCell className={`text-right tabular-nums ${WIDE}`}>{formatNumber(Math.round(h.avg_price))}</TableCell>
          <TableCell className="text-right tabular-nums">{h.last_close == null ? '-' : formatNumber(h.last_close)}
            {h.price_source === 'live' && h.quoted_at && <span className="block text-caption text-muted-foreground">장중 {h.quoted_at.slice(11, 16)}</span>}</TableCell>
          <TableCell className={`text-right tabular-nums ${tone(h.return_pct)}`}>{formatPercent(h.return_pct)}</TableCell>
          <TableCell className={`text-right tabular-nums ${tone(h.day_change_pct)}`}>{formatPercent(h.day_change_pct)}</TableCell>
        </TableRow>)}
        <TableRow><TableCell className="text-muted-foreground">현금</TableCell><TableCell className="text-right tabular-nums">{formatRatio(data.cash_weight_pct)}</TableCell><TableCell colSpan={4} /></TableRow>
      </TableBody></Table>
    </CardContent></Card>

    {data.closed.length > 0 && <Card><CardHeader><CardTitle>청산 내역</CardTitle></CardHeader><CardContent>
      <Table className={COMPACT}><TableHeader><TableRow>
        <TableHead>종목</TableHead><TableHead>보유 기간</TableHead><TableHead className={`text-right ${WIDE}`}>평단</TableHead>
        <TableHead className={`text-right ${WIDE}`}>매도가</TableHead><TableHead className="text-right">실현 수익률</TableHead><TableHead className="text-right">구분</TableHead>
      </TableRow></TableHeader><TableBody>
        {data.closed.map(c => <TableRow key={`${c.code}-${c.sell_date}-${c.sell_price}`}>
          <TableCell className="font-medium">{c.name}</TableCell>
          <TableCell className="tabular-nums text-muted-foreground whitespace-normal md:whitespace-nowrap">{c.entry_date} → {c.sell_date}{c.holding_days != null && <span className="block text-caption">{formatNumber(c.holding_days)}일</span>}</TableCell>
          <TableCell className={`text-right tabular-nums ${WIDE}`}>{formatNumber(Math.round(c.avg_price))}</TableCell>
          <TableCell className={`text-right tabular-nums ${WIDE}`}>{formatNumber(c.sell_price)}</TableCell>
          <TableCell className={`text-right tabular-nums ${tone(c.return_pct)}`}>{formatPercent(c.return_pct)}</TableCell>
          <TableCell className="text-right text-muted-foreground">{c.full ? '전량' : '일부'}</TableCell>
        </TableRow>)}
      </TableBody></Table>
    </CardContent></Card>}

    {selected ? <section ref={detailRef} className="scroll-mt-4 space-y-3" aria-label="보유 종목 상세">
      <SegmentTabs tabs={data.holdings.map(h => ({ value: h.code, label: h.name }))} value={selected.code} onChange={code => select(code)} />
      <HoldingDetail key={selected.code} holding={selected} />
    </section>
      : <p className="text-sm text-muted-foreground">지금 보유 중인 종목이 없습니다. 현금과 청산 내역만 표시합니다.</p>}
  </>
}
