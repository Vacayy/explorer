import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { ErrorState } from '@/components/shared/ErrorState'
import { usePortfolioExposure } from '@/hooks/usePortfolio'
import { formatRatio } from '@/utils/format'
import type { PortfolioHolding } from '@/types'

const SOURCE = { graph: '인과 그래프', comention: '함께 언급', chain: '밸류체인' } as const
const SOURCE_HELP = {
  graph: '근거 문서가 있는 인과 관계(2단계까지)',
  comention: '최근 180일 같은 문서에 자주 함께 붙은 주제(시황 나열 글은 낮게 반영)',
  chain: '같은 밸류체인에 속함',
} as const
const DIRECTION: Record<string, { label: string; cls: string }> = {
  '+': { label: '수혜 요인', cls: 'text-up' },
  '−': { label: '부담 요인', cls: 'text-down' },
  '+−': { label: '영향 엇갈림', cls: 'text-muted-foreground' },
}

/** 공통 변수 — 종목 비중이 아니라 '무엇에 걸려 있나'의 비중(portfolio-intelligence §1). */
export function ExposureCard({ holdings }: { holdings: PortfolioHolding[] }) {
  const exposure = usePortfolioExposure()
  const [all, setAll] = useState(false)
  const name = (code: string) => holdings.find(h => h.code === code)?.name ?? code
  const drivers = exposure.data?.drivers ?? []
  const thin = Object.entries(exposure.data?.coverage ?? {}).filter(([, c]) => c.graph === 0)
  return <TooltipProvider><Card>
    <CardHeader>
      <CardTitle>공통 변수</CardTitle>
      <CardDescription>보유 종목들이 함께 기대는 변수와 그 변수에 걸린 비중입니다. 계산만 하며 AI 판단은 없습니다.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-3">
      {exposure.isPending ? <Skeleton className="h-48 w-full" />
        : exposure.isError ? <ErrorState onRetry={() => void exposure.refetch()} />
        : !drivers.length ? <p className="text-sm text-muted-foreground">공통 변수를 찾을 근거가 아직 없습니다. 인과 그래프 연결과 함께 언급된 자료가 쌓이면 표시합니다.</p>
        : <>
          <ul className="divide-y">{(all ? drivers : drivers.slice(0, 8)).map(d => {
            const dir = d.direction ? DIRECTION[d.direction] : null
            return <li key={d.key} className="grid gap-1.5 py-2.5 @2xl/portfolio:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] @2xl/portfolio:items-center @2xl/portfolio:gap-4">
              <div className="min-w-0 space-y-1">
                <p className="flex flex-wrap items-center gap-x-2 text-sm font-medium">{d.name}
                  {dir && <span className={`text-caption font-normal ${dir.cls}`}>{dir.label}</span>}</p>
                <div className="flex flex-wrap gap-1">
                  {d.sources.map(s => <Tooltip key={s}><TooltipTrigger asChild>
                    <Badge variant="outline" className="text-caption font-normal text-muted-foreground">{SOURCE[s]}</Badge>
                  </TooltipTrigger><TooltipContent>{SOURCE_HELP[s]}{s === 'graph' && d.confidence != null ? ` · 신뢰도 ${d.confidence}` : ''}</TooltipContent></Tooltip>)}
                </div>
              </div>
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2"><Progress value={d.exposure_pct} aria-label={`${d.name} 노출 ${formatRatio(d.exposure_pct)}`} className="h-1.5" />
                  <span className="w-12 shrink-0 text-right text-sm tabular-nums">{formatRatio(d.exposure_pct)}</span></div>
                <p className="truncate text-caption text-muted-foreground">{d.holdings.map(name).join(' · ')}</p>
              </div>
            </li>
          })}</ul>
          {drivers.length > 8 && <Button variant="ghost" size="sm" onClick={() => setAll(!all)}>{all ? '접기' : `${drivers.length - 8}개 더 보기`}</Button>}
          {thin.length > 0 && <p className="text-caption text-muted-foreground">
            {thin.map(([code]) => name(code)).join(' · ')}은 인과 그래프 연결이 없어 함께 언급·밸류체인으로만 반영했습니다.</p>}
        </>}
    </CardContent>
  </Card></TooltipProvider>
}
