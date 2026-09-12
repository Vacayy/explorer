import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'

type Point = readonly [string, number]

/** Pointer preview and click/touch/keyboard disclosure share the same chart. */
export function MetricTrend({ label, points = [], format = String, children, className }: {
  label: string; points?: readonly Point[]; format?: (value: number) => string;
  children: ReactNode; className?: string;
}) {
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pinned = useRef(false)
  const clear = () => clearTimeout(timer.current)
  useEffect(() => () => clearTimeout(timer.current), [])
  const change = (value: boolean) => { clear(); pinned.current = value; setOpen(value) }
  const enter = () => { clear(); timer.current = setTimeout(() => setOpen(true), 220) }
  const leave = () => { clear(); if (!pinned.current) timer.current = setTimeout(() => setOpen(false), 180) }
  const data = points.filter(([, value]) => Number.isFinite(value))
  const values = data.map(([, value]) => value)
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1
  const path = data.map(([, value], i) => `${12 + i / Math.max(1, data.length - 1) * 256},${104 - (value - lo) / span * 88}`).join(' ')
  return <Popover open={open} onOpenChange={change}>
    <PopoverTrigger asChild>
      <Button variant="ghost" className={className} aria-label={`${label} 추이 보기`}
        onPointerEnter={e => { if (e.pointerType === 'mouse') enter() }} onPointerLeave={leave}>
        {children}
      </Button>
    </PopoverTrigger>
    <PopoverContent side="bottom" sideOffset={8} collisionPadding={12} aria-label={`${label} 추이`}
      className="w-[304px] max-w-[calc(100vw-24px)] gap-2 rounded-2xl p-4"
      onOpenAutoFocus={e => e.preventDefault()} onCloseAutoFocus={e => e.preventDefault()}
      onPointerEnter={clear} onPointerLeave={leave}>
      <div className="flex items-baseline justify-between gap-3"><h3 className="text-sm font-semibold">{label}</h3><span className="text-sm font-medium tabular-nums">{data.length ? format(data.at(-1)![1]) : '—'}</span></div>
      {data.length > 1 ? <>
        <div className="flex justify-between text-caption text-muted-foreground tabular-nums"><span>최저 {format(lo)}</span><span>최고 {format(hi)}</span></div>
        <svg viewBox="0 0 280 120" className="h-28 w-full text-primary" role="img" aria-label={`${label}, ${data[0][0]}부터 ${data.at(-1)![0]}까지 ${data.length}개 관측 추이`}>
          <path d="M12 16H268M12 60H268M12 104H268" fill="none" stroke="currentColor" strokeOpacity="0.1" />
          <polyline points={path} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {data.map(([date, value], i) => <circle key={`${date}-${i}`} cx={12 + i / (data.length - 1) * 256} cy={104 - (value - lo) / span * 88} r="4" fill="transparent"><title>{date} · {format(value)}</title></circle>)}
        </svg>
        <div className="flex justify-between text-caption text-muted-foreground"><span>{data[0][0]}</span><span>{data.at(-1)![0]}</span></div>
        <p className="text-caption text-muted-foreground">최근 {data.length}개 관측 · 관측 순서 기준 · 저장값</p>
      </> : <p className="py-6 text-sm text-muted-foreground">{data.length ? '추이를 그릴 관측값이 더 필요합니다.' : '저장된 추이 데이터가 없습니다.'}</p>}
    </PopoverContent>
  </Popover>
}
