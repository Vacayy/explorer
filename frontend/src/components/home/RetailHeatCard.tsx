import { HomeBlock } from '@/components/home/HomeSection'
import { BlockError, RowsSkeleton } from '@/components/home/blockState'
import { MetricTable, RegimeBadge } from '@/components/retail/retailFormat'
import { useRetailSummary } from '@/hooks/useRetail'
import { formatKrw, formatLevel } from '@/utils/format'

/**
 * 홈 › 한국 시장 — 개인 투자 열기 (D-231, ia-redesign §4.17). 국면 배지 · 신용융자·예탁금·코스피 · 판정 근거 ·
 * 지표 11개(5년 백분위 막대 · 20일 변화) · '추이 보기 ›'(/retail). 오류는 이 블록 단위로만 낸다(§4.28).
 */
export function RetailHeatCard() {
  const q = useRetailSummary()
  const d = q.data
  return (
    <HomeBlock section label="retail.heat" title="개인 투자 열기" link={{ to: '/retail', label: '추이 보기' }}
      info="빚투·대기자금·거래 열기의 변화 속도를 과거 5년과 비교합니다. 평일 18:30에 금융투자협회 통계를 받습니다."
      asOf={d?.as_of ?? null}>
      {!d ? (q.isError ? <BlockError message="개인 투자 열기 지표를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} /> : <RowsSkeleton rows={6} />)
        : !d.regime ? <p role="status" className="text-sm text-muted-foreground">아직 수집된 자료가 없습니다. 평일 18:30에 받습니다.</p>
        : <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <RegimeBadge regime={d.regime} />
            <span className="text-muted-foreground">
              신용융자 <span className="text-foreground tabular-nums">{formatKrw(d.levels.credit_total)}</span>
              {' · '}예탁금 <span className="text-foreground tabular-nums">{formatKrw(d.levels.deposits)}</span>
              {' · '}코스피 <span className="text-foreground tabular-nums">{formatLevel(d.levels.kospi_close)}</span>
            </span>
          </div>
          {!!d.regime.reasons.length && <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-muted-foreground marker:text-muted-foreground/60">
            {d.regime.reasons.map(r => <li key={r}>{r}</li>)}
          </ul>}
          <div className="text-[13px] [&_td]:py-1.5 [&_th]:h-8 [&_th]:text-xs [&_th]:text-muted-foreground"><MetricTable metrics={d.metrics} /></div>
        </div>}
    </HomeBlock>
  )
}
