import { QueryState } from "@/components/shared/QueryState"
import { ArrowUpRight } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { InfoTip } from '@/components/shared/InfoTip'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { usePortfolioEvents } from '@/hooks/usePortfolio'

export const EVENT_KIND: Record<string, string> = { ir: 'IR', earnings_notice: '실적 예고', agm: '주총', earnings_est: '실적', report_deadline: '보고서', us_earnings: '해외 실적' }

export function dday(date: string) {
  const today = new Date(new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10))
  const n = Math.round((new Date(date).getTime() - today.getTime()) / 86_400_000)
  return n === 0 ? '오늘' : `D-${n}`
}

/** 이름을 따로 굵게 보이므로 제목 앞의 같은 이름은 뺀다 */
const eventText = (e: { title: string; name: string | null }) => e.name && e.title.startsWith(e.name) ? e.title.slice(e.name.length).replace(/^[\s·:-]+/, '') || e.title : e.title

const TAG = 'inline-flex h-[22px] items-center whitespace-nowrap rounded-md px-2 text-xs font-medium'

/** 시안 States: 빈 상태 = 회색 상자(surface-2 + line-2 테두리, 여백 14) */
function EmptyBox({ children }: { children: string }) {
  return <p role="status" className="border border-line-2 bg-surface-2 p-3.5 text-[13px] text-ink-2">{children}</p>
}

/** 다가오는 이벤트(45일) — 시안 Portfolio-Events 두 칸: 보유 종목 일정(확정·예상) | 관련 해외 기업 실적(먼저 나오는 숫자). */
export function EventsCard() {
  const events = usePortfolioEvents()
  const items = events.data ?? []
  const mine = items.filter(e => e.kind !== 'us_earnings')
  const overseas = items.filter(e => e.kind === 'us_earnings')
  return <TooltipProvider><QueryState query={events} loading={<Skeleton className="h-48 w-full" />} isEmpty={() => false}>{() => <div className="surface-grid grid items-stretch lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
    <Card aria-label="다가오는 이벤트"><CardContent className="flex flex-col gap-3 py-4">
      <h2 className="flex items-baseline gap-2.5 text-[15px] font-semibold">다가오는 이벤트<span className="inline-flex items-center text-xs font-normal text-ink-3">보유 종목 · 45일 안<InfoTip label="이벤트 설명">공시 확정과 지난해 패턴 추정을 구분해 표시합니다. 일정 수집은 평일 16:50에 갱신됩니다.</InfoTip></span></h2>
      {!mine.length ? <EmptyBox>45일 안에 확인된 보유 종목 일정이 없습니다.</EmptyBox>
        : <ul>{mine.map((e, i) => <li key={`${e.date}-${e.kind}-${e.title}`} className="grid grid-cols-[52px_48px_minmax(0,1fr)_auto] items-center gap-3 border-t py-2.5 text-[13.5px] md:grid-cols-[64px_140px_minmax(0,1fr)_auto]">
            <span className={`font-mono text-[15px] tabular-nums ${i === 0 ? 'text-up-ink' : 'text-ink'}`}>{dday(e.date)}</span>
            <span className="font-mono tabular-nums text-ink-3">{e.date.slice(5).replace('-', '/')}</span>
            <span className="min-w-0">{e.name && <><b className="font-semibold">{e.name}</b> · </>}{e.url
              ? <a href={e.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{eventText(e)}<ArrowUpRight aria-hidden="true" className="ml-0.5 inline size-3" /></a>
              : eventText(e)}</span>
            {e.estimated ? <Tooltip><TooltipTrigger asChild><span tabIndex={0} className={`${TAG} border border-line-2 text-ink-2`}>예상</span></TooltipTrigger><TooltipContent>{e.basis ?? '추정'}</TooltipContent></Tooltip>
              : <span className={`${TAG} bg-fact-tint text-fact`}>확정</span>}
          </li>)}</ul>}
    </CardContent></Card>
    <Card aria-label="관련 해외 기업"><CardContent className="flex flex-col gap-3 py-4">
      <h2 className="flex items-baseline gap-2.5 text-[15px] font-semibold">관련 해외 기업<span className="text-xs font-normal text-ink-3">먼저 나오는 숫자</span></h2>
      {!overseas.length ? <EmptyBox>45일 안에 관련 해외 기업 실적 발표가 없습니다.</EmptyBox>
        : <ul>{overseas.map(e => <li key={`${e.date}-${e.title}`} className="grid grid-cols-[52px_minmax(0,1fr)] gap-3 border-t py-2.5 text-[13px] md:grid-cols-[64px_minmax(0,1fr)]">
            <span className="font-mono tabular-nums text-ink-2">{dday(e.date)}</span>
            <span className="min-w-0">{e.code && <span className="mr-2 font-mono font-semibold tabular-nums">{e.code}</span>}{e.title} <span className="font-mono tabular-nums text-ink-3">{e.date.slice(5).replace('-', '/')}</span></span>
          </li>)}</ul>}
    </CardContent></Card>
  </div>}</QueryState></TooltipProvider>
}
