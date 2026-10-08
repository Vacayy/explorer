import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useMacro } from '@/hooks/useMacro'
import { useMarketRegime } from '@/hooks/useMarketRegime'
import { MarketRegime } from '@/components/home/MarketRegime'
import { MacroLiquidity, fmtValue } from '@/components/home/MacroLiquidity'
import { formatNumber, formatPercent, formatPp } from '@/utils/format'
import { MetricTrend } from '@/components/shared/MetricTrend'

const metrics = [
  ['usdkrw', '달러/원'], ['jpykrw', '엔/원(100엔)'], ['us2y', '미국 2Y'], ['us10y', '미국 10Y'],
  ['oil', 'WTI 유가'], ['gold', '금'], ['btc', '비트코인'],
]
/** 기준일로부터 한 달 전(그 날 이전 마지막 관측)과 비교. 금리(pct)는 %p, 나머지는 %. */
function monthOverMonth(points: [string, number][] | undefined, rate: boolean): { text: string; sign: number } | null {
  const last = points?.at(-1)
  if (!points || !last) return null
  const ago = new Date(`${last[0]}T00:00:00Z`); ago.setUTCMonth(ago.getUTCMonth() - 1)
  const cutoff = ago.toISOString().slice(0, 10)
  const base = [...points].reverse().find(([d]) => d <= cutoff)
  if (!base || (!rate && base[1] === 0)) return null
  const diff = rate ? last[1] - base[1] : ((last[1] - base[1]) / base[1]) * 100
  return { text: `MoM ${rate ? formatPp(diff) : formatPercent(diff)}`, sign: Math.sign(diff) }
}
export function MarketContext() {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem('explorer.market.context') === 'expanded' } catch { return false } })
  const macro = useMacro(), regime = useMarketRegime()
  return <Collapsible open={open} onOpenChange={value => { setOpen(value); try { localStorage.setItem('explorer.market.context', value ? 'expanded' : 'compact') } catch { /* private storage */ } }} className="market-context">
    <div className="market-context-summary">
      <div className="market-metric-strip" tabIndex={0} role="region" aria-label="주요 시장 지표 가로 스크롤">
        {metrics.map(([key, label]) => { const metric = macro.data?.items.find(item => item.key === key); return <Metric key={key} points={metric?.dated_series} format={metric ? v => fmtValue({ ...metric, value: v }) : undefined} label={label} value={metric ? fmtValue(metric) : null} mom={monthOverMonth(metric?.dated_series, metric?.fmt === 'pct')} date={metric?.as_of} loading={macro.isLoading} failed={macro.isError} /> })}
      </div>
      <CollapsibleTrigger asChild><Button variant="ghost" size="sm" aria-label={open ? '시장 지표 상세 접기' : '시장 지표 상세 펼치기'}>{open ? '접기' : '상세'}<ChevronDown aria-hidden="true" className={open ? 'rotate-180' : ''} /></Button></CollapsibleTrigger>
    </div>
    <CollapsibleContent className="border-t p-3">
      {(macro.isError || regime.isError) && <div className="mb-3 flex flex-wrap gap-2" role="alert"><span className="text-sm text-muted-foreground">일부 지표를 불러오지 못했습니다.</span><Button variant="outline" size="sm" onClick={() => { void macro.refetch(); void regime.refetch() }}>조회 다시 시도</Button></div>}
      <div className="market-context-details"><div className="@container/market min-w-0"><MarketRegime /></div><div className="@container/market min-w-0"><MacroLiquidity /></div></div>
      <p className="mt-3 text-caption text-muted-foreground">지표별 기준일이 다를 수 있습니다. 최신 저장값이며 실시간 시세가 아닙니다. 갱신 버튼은 지표를 재수집합니다.</p>
    </CollapsibleContent>
  </Collapsible>
}
function Metric({ label, value, mom, date, loading, failed, points, format = formatNumber }: { label: string; value: string | null; mom: { text: string; sign: number } | null; date?: string; loading: boolean; failed: boolean; points?: [string, number][]; format?: (value: number) => string }) {
  return <MetricTrend label={label} points={points} format={format} className="market-metric h-auto items-start gap-0 rounded-lg px-2 py-1 text-left font-normal"><span className="text-caption text-muted-foreground">{label}</span><span className="text-sm font-medium tabular-nums">{loading ? '…' : value ?? (failed ? '조회 실패' : '미수집')}</span>{mom && <span className={`text-caption tabular-nums ${mom.sign > 0 ? 'text-up' : mom.sign < 0 ? 'text-down' : 'text-muted-foreground'}`}>{mom.text}</span>}<span className="text-caption text-muted-foreground">{date ? `${date.slice(5)} 기준` : value ? '기준일 미상' : '—'}</span></MetricTrend>
}
