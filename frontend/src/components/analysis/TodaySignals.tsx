import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { LoaderCircle } from 'lucide-react'
import { toast } from 'sonner'
import { fetchSpineSignals, spineKeys } from '@/api/spine'
import { useSignalsSummary, useSpineSignals } from '@/hooks/useSpineSignals'
import { ErrorState } from '@/components/shared/ErrorState'
import { InfoTip } from '@/components/shared/InfoTip'
import { SIGNAL_LABEL, SignalCard, signalEntityPath } from '@/components/shared/SignalCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { signalUniverse, type DraftUniverse } from '@/components/analysis/discoveryDraft'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/utils/format'

/** 신호 유형 — 카드 순서. call_momentum(실적 발언 모멘텀)은 미국 기업 실적 시즌 신호 (옛 /explore 신호 탭, explore-core §2) */
export const SIGNAL_TYPES = ['mention_surge', 'theme_surge', 'neglect', 'high_52w', 'volume_spike', 'quadrant_gap', 'consensus_extreme', 'call_momentum'] as const
const TYPE_DESC: Record<string, string> = {
  mention_surge: '직전 7일보다 언급이 크게 늘어난 종목',
  theme_surge: '여러 소스가 지금 몰리는 주제',
  neglect: '저평가·흑자인데 30일 언급이 없는 종목',
  high_52w: '52주 전고점을 넘긴 종목',
  volume_spike: '60일 평균의 몇 배 거래가 터진 날',
  quadrant_gap: '주가와 관측 감성이 엇갈리는 종목',
  consensus_extreme: '감성이 한쪽으로 쏠린 종목',
  call_momentum: '실적 발표에서 새로 생기거나 빨라진 성장 동인',
}
/** 목록 기간 — 매일 도는 신호는 30일, 주제는 14일, 실적 시즌 신호는 한 시즌(90일) */
const LIST_DAYS: Record<string, number> = { theme_surge: 14, call_momentum: 90 }
const listDays = (type: string) => LIST_DAYS[type] ?? 30
const shortDate = (iso: string) => iso.slice(5).replace('-', '/')

function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b + 'T00:00:00').getTime() - new Date(a + 'T00:00:00').getTime()) / 86_400_000)
}

/**
 * 종목 발견 첫 화면 '오늘의 신호'(ia-redesign §4.19·§4.32, 옛 탐색 › 신호 흡수).
 * '이 신호로 찾기'는 그 신호의 최신일 국내 종목을 검색 범위로 넘겨 조건을 더 쌓게 한다. 국내 종목이 없는 신호(주제·미국)는 목록을 연다.
 */
export function TodaySignals({ onUniverse, onOpenList }: { onUniverse: (universe: DraftUniverse) => void; onOpenList: (type: string) => void }) {
  const summary = useSignalsSummary(7)
  const client = useQueryClient()
  const [finding, setFinding] = useState<string | null>(null)
  const byType = new Map((summary.data?.types ?? []).map(t => [t.type, t]))
  // 옛 /explore 링크(→ #signals)는 카드가 그려진 뒤 이 블록으로 내린다
  const { hash } = useLocation()
  const ready = !!summary.data
  useEffect(() => {
    if (hash !== '#signals' || !ready) return
    const t = window.setTimeout(() => document.getElementById('signals')?.scrollIntoView({ block: 'start' }), 50)
    return () => window.clearTimeout(t)
  }, [hash, ready])
  async function find(type: string) {
    setFinding(type)
    try {
      const data = await client.fetchQuery({ queryKey: spineKeys.signals(type, listDays(type)), queryFn: () => fetchSpineSignals(type, listDays(type)), staleTime: 5 * 60_000 })
      const universe = signalUniverse(SIGNAL_LABEL[type] ?? type, data.items)
      if (universe) onUniverse(universe)
      else onOpenList(type)
    } catch {
      toast.error('신호 종목을 불러오지 못했습니다.')
    } finally { setFinding(null) }
  }
  return <section id="signals" aria-label="오늘의 신호" className="scroll-mt-4 space-y-2.5">
    <h2 className="flex items-center gap-1 text-section font-semibold">오늘의 신호
      {summary.data?.as_of && <span className="text-caption font-normal tabular-nums text-muted-foreground md:hidden">{shortDate(summary.data.as_of)}</span>}
      <InfoTip label="오늘의 신호 설명">매일 계산되는 관찰 신호입니다. 숫자는 유형별 최신일 건수입니다. '이 신호로 찾기'를 누르면 그 종목들을 검색 범위로 넘겨 조건을 더 쌓을 수 있습니다.</InfoTip>
    </h2>
    {summary.isPending ? <div className="grid grid-cols-2 border xl:grid-cols-4">{SIGNAL_TYPES.map(type => <div key={type} className="space-y-2 border-b border-r p-3"><Skeleton className="h-4 w-24" /><Skeleton className="h-3 w-40 max-md:w-20" /><Skeleton className="h-6 w-32" /></div>)}</div>
      : summary.isError || !summary.data ? <ErrorState message="오늘의 신호를 불러오지 못했습니다." onRetry={() => summary.refetch()} />
      : !summary.data.types.length ? <p role="status" className="border p-4 text-sm text-muted-foreground">아직 계산된 신호가 없습니다.</p>
      : <ul className="grid grid-cols-2 border-l border-t xl:grid-cols-4 max-md:gap-2 max-md:border-0">
        {SIGNAL_TYPES.map(type => {
          const t = byType.get(type)
          const stale = !!t && !!summary.data.as_of && daysBetween(t.latest_date, summary.data.as_of) > 2
          return <li key={type} className="flex min-w-0 flex-col gap-1.5 border-b border-r bg-card px-3.5 py-3 max-md:gap-1 max-md:rounded-xl max-md:border max-md:p-3">
            <div className="flex items-baseline gap-2">
              <button type="button" className="min-w-0 truncate text-left text-[13.5px] font-semibold hover:underline max-md:text-[13px]" onClick={() => onOpenList(type)}>{SIGNAL_LABEL[type] ?? type}</button>
              <span className="ml-auto font-mono text-lg tabular-nums max-md:text-base">{t ? formatNumber(t.count_latest) : 0}</span>
            </div>
            <p className="line-clamp-1 text-caption text-muted-foreground max-md:hidden">{TYPE_DESC[type]}{t && <> · <span className={cn('tabular-nums', stale && 'text-chart-warning')}>{shortDate(t.latest_date)}</span></>}</p>
            {t?.top.length ? <>
              <div className="flex flex-wrap gap-1 max-md:hidden">{t.top.filter((x, i, all) => all.findIndex(y => y.name === x.name) === i).map(x => <Badge key={x.entity_id} variant="outline" asChild><Link to={signalEntityPath(x)}>{x.name}</Link></Badge>)}</div>
              <p className="line-clamp-2 text-caption text-ink-2 md:hidden">{[...new Set(t.top.map(x => x.name))].join(' · ')}</p>
              <p className={cn('text-[11px] text-muted-foreground md:hidden', stale && 'text-chart-warning')}>{shortDate(t.latest_date)}</p>
            </> : <p className="text-caption text-muted-foreground">신호 없음</p>}
            <Button variant="ghost" size="xs" className="mt-auto h-auto self-start px-0 py-0 text-caption font-normal hover:bg-transparent hover:text-ink max-md:h-9" disabled={!t || finding === type} onClick={() => void find(type)}>
              {finding === type ? <LoaderCircle className="size-3 animate-spin" /> : null}이 신호로 찾기 ›
            </Button>
          </li>
        })}
      </ul>}
  </section>
}

/** 신호 목록 시트 — 옛 /explore?list=<type>. 국내 종목이면 '이 종목들로 찾기' */
export function SignalListSheet({ type, onClose, onUniverse }: { type: string | null; onClose: () => void; onUniverse: (universe: DraftUniverse) => void }) {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const list = useSpineSignals(type ?? undefined, type ? listDays(type) : undefined)
  const items = type ? list.data?.items ?? [] : []
  const shown = items.slice(0, page * 12)
  const universe = type ? signalUniverse(SIGNAL_LABEL[type] ?? type, items) : null
  return <Sheet open={!!type} onOpenChange={open => { if (!open) { setPage(1); onClose() } }}>
    <SheetContent className="w-full overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
      <SheetHeader>
        <SheetTitle>{type ? SIGNAL_LABEL[type] ?? type : '신호'}</SheetTitle>
        <SheetDescription>{type ? `${TYPE_DESC[type] ?? ''} · 최근 ${listDays(type)}일 ${formatNumber(items.length)}건` : ''}</SheetDescription>
      </SheetHeader>
      <div className="space-y-3 px-4 pb-6">
        {universe && <Button className="w-full" onClick={() => onUniverse(universe)}>최신일 {formatNumber(universe.codes.length)}종목으로 찾기</Button>}
        {list.isPending ? <div className="space-y-2">{[0, 1, 2].map(i => <Skeleton key={i} className="h-24 w-full" />)}</div>
          : list.isError ? <ErrorState message="신호 목록을 불러오지 못했습니다." onRetry={() => list.refetch()} />
          : !items.length ? <p role="status" className="py-6 text-center text-sm text-muted-foreground">이 신호는 아직 없습니다.</p>
          : <>
            <div className="surface-grid grid grid-cols-1">{shown.map(signal => <SignalCard key={signal.id} signal={signal} onKeywordClick={keyword => navigate(`/feed?topic=${encodeURIComponent(keyword)}`)} />)}</div>
            {shown.length < items.length && <Button variant="outline" size="sm" className="w-full" onClick={() => setPage(p => p + 1)}>{formatNumber(items.length - shown.length)}건 더 보기</Button>}
          </>}
      </div>
    </SheetContent>
  </Sheet>
}
