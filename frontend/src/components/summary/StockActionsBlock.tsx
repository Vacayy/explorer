import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { BlockHead } from '@/components/home/HomeSection'
import { useActions, useRights } from '@/hooks/useActions'
import { useCompanyPrices } from '@/hooks/useCompanyPrices'
import { useCompanyEvidence } from '@/hooks/useCompanyEvidence'
import { useIsMobile } from '@/hooks/use-mobile'
import { disclosureTag, lastClose, shortDate } from '@/lib/dossier'
import { cn } from '@/lib/utils'
import { formatNumber, formatPercent, formatStockPrice } from '@/utils/format'
import type { RightsRow } from '@/types'

const ymd = (d: string) => `${d.slice(2, 4)}.${d.slice(4, 6)}.${d.slice(6, 8)}`
const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' })

/**
 * 국내 도시에 개요 맨 아래 '기업활동'(#actions, ia-redesign §4.13·§10.6 — 옛 /actions?code=X).
 * 최근 180일 기업활동(유·무상증자·합병·분할…) · 유상증자면 발행가 대비 현재가(머리·차트와 같은 저장 종가)
 * · 최근 14일 주주환원·실적·대량보유/임원 지분 공시(같은 목록 칸). 저장분만 읽는다(LLM·외부 호출 0).
 */
export function StockActionsBlock({ stockCode }: { stockCode: string }) {
  const mobile = useIsMobile()
  const actions = useActions({ stockCode, days: 180, kind: 'all' })
  const rights = useRights()
  const prices = useCompanyPrices(stockCode, 'kr')
  const recent = useCompanyEvidence({ company: stockCode, market: 'kr', source: 'disclosure', start: daysAgo(14), size: 50 })
  const last = lastClose(prices.data?.items)
  const right = rights.data?.items.find((r) => r.stock_code === stockCode) ?? null
  const acts = actions.data?.items ?? []
  const filings = (recent.data?.items ?? [])
    .map((d) => ({ d, tag: disclosureTag(d.title) }))
    .filter((x) => x.tag)
    .slice(0, mobile ? 3 : 8)
  const loading = actions.isPending || recent.isPending
  return (
    <Card className="gap-0 py-0" data-stock-actions>
      <BlockHead title="기업활동" info="최근 180일 DART 기업활동 공시(유·무상증자·합병·분할·공개매수·감자)와 최근 14일 주주환원·실적·지분 공시입니다. 발행가 대비는 차트와 같은 마지막 저장 종가로 계산합니다."
        link={{ to: `/analyze/${stockCode}/mentions?source=disclosure`, label: '공시 전체' }} />
      <div className="space-y-4 p-3">
        {right && last && <RightsLine row={right} close={last.close} date={last.date} />}
        {loading ? <div role="status" aria-label="기업활동 불러오는 중" className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
          : <>
            <section aria-label="최근 180일 기업활동">
              {actions.isError ? <ErrorState message="기업활동을 불러오지 못했습니다" onRetry={() => actions.refetch()} />
                : acts.length === 0 ? <p className="text-sm text-muted-foreground">최근 180일 기업활동 공시가 없습니다.</p>
                : <ul className="divide-y">
                  {acts.map((a) => (
                    <li key={a.id} className="grid grid-cols-[4.5rem_1fr] gap-x-3 py-2 text-sm sm:grid-cols-[4.5rem_auto_1fr]">
                      <span className="font-mono text-caption tabular-nums text-muted-foreground">{ymd(a.rcept_dt)}</span>
                      <span className="flex items-start gap-1">
                        <Badge variant="secondary" className={cn('text-[10px]', a.action_type === '유상증자' && 'bg-down/10 text-down', a.action_type === '무상증자' && 'bg-up/10 text-up')}>{a.action_type}</Badge>
                        {a.is_correction && <Badge variant="outline" className="text-[10px] text-muted-foreground">정정</Badge>}
                      </span>
                      <a href={a.dart_url} target="_blank" rel="noreferrer" className="col-start-2 min-w-0 hover:underline sm:col-start-auto">
                        {a.summary || a.report_nm}
                      </a>
                    </li>
                  ))}
                </ul>}
            </section>
            <section aria-label="주주환원·실적 공시 최근 14일" className="space-y-1">
              <h3 className="text-caption font-medium text-muted-foreground">주주환원·실적·지분 공시 · 최근 14일</h3>
              {recent.isError ? <ErrorState message="최근 공시를 불러오지 못했습니다" onRetry={() => recent.refetch()} />
                : filings.length === 0 ? <p className="text-sm text-muted-foreground">최근 14일에 해당 공시가 없습니다.</p>
                : <ul className="divide-y">
                  {filings.map(({ d, tag }) => (
                    <li key={d.id} className="grid grid-cols-[4.5rem_1fr_auto] items-baseline gap-x-3 py-2 text-sm">
                      <span className="font-mono text-caption tabular-nums text-muted-foreground">{d.local_date.slice(2).replaceAll('-', '.')}</span>
                      {d.url ? <a href={d.url} target="_blank" rel="noreferrer" className="min-w-0 hover:underline">{d.title}</a> : <span className="min-w-0">{d.title}</span>}
                      <Badge variant="outline" className="text-[10px] font-normal">{tag}</Badge>
                    </li>
                  ))}
                </ul>}
            </section>
          </>}
      </div>
    </Card>
  )
}

/** 유·무상증자 발행가 대비 현재가 한 줄 — 확정 > 2차 > 1차 발행가 */
function RightsLine({ row, close, date }: { row: RightsRow; close: number; date: string }) {
  const price = row.price_final ?? row.price_2nd ?? row.price_1st
  if (!price) return null
  const stage = row.price_final ? '확정' : row.price_2nd ? '2차' : '1차'
  const diff = ((close - price) / price) * 100
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 bg-muted/60 px-3 py-2 text-sm" data-rights-line>
      <span className="font-medium">{row.action_type ?? '증자'} 발행가 <span className="font-mono tabular-nums">{formatNumber(price)}원</span></span>
      <span className="text-caption text-muted-foreground">{stage}{row.date_price_fix ? ` ${row.date_price_fix}` : ''}{row.method ? ` · ${row.method}` : ''}</span>
      <span>{shortDate(date)} 종가 <span className="font-mono tabular-nums">{formatStockPrice(close, 'kr')}</span> — 발행가 대비 <span className={cn('font-mono tabular-nums', diff > 0 ? 'text-up' : diff < 0 ? 'text-down' : '')}>{formatPercent(diff)}</span></span>
    </p>
  )
}
