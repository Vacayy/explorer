import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'

/** Native scrolling + snap, with equivalent buttons for mouse/keyboard users. */
export function HorizontalCarousel({ label, children, footer }: { label: string; children: ReactNode; footer?: ReactNode }) {
  const id = useId()
  const viewport = useRef<HTMLDivElement>(null)
  const [edges, setEdges] = useState({ previous: false, next: false })
  useEffect(() => {
    const el = viewport.current
    if (!el) return
    const update = () => setEdges({ previous: el.scrollLeft > 1, next: el.scrollLeft + el.clientWidth < el.scrollWidth - 1 })
    const observer = new ResizeObserver(update)
    observer.observe(el)
    for (const child of el.children) observer.observe(child)
    el.addEventListener('scroll', update, { passive: true })
    update()
    return () => { observer.disconnect(); el.removeEventListener('scroll', update) }
  }, [children])
  function move(direction: number) {
    const el = viewport.current
    if (!el) return
    el.scrollBy({ left: direction * el.clientWidth * 0.8, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
  }
  return (
    <div className="min-w-0 space-y-2">
      <div ref={viewport} id={id} role="region" aria-roledescription="캐러셀" aria-label={label} tabIndex={0}
        className="flex snap-x snap-mandatory gap-4 overflow-x-auto overscroll-x-contain pb-2 focus-visible:outline-2 focus-visible:outline-ring">
        {children}
      </div>
      {(footer || edges.previous || edges.next) && <div className="flex flex-wrap items-center justify-between gap-2">
        {footer && <div className="min-w-0 flex-1">{footer}</div>}
        {(edges.previous || edges.next) && <div className="ml-auto flex shrink-0 gap-2">
        <Button variant="outline" size="icon-sm" aria-label={`이전 ${label}`} aria-controls={id} disabled={!edges.previous} onClick={() => move(-1)}><ChevronLeft aria-hidden="true" className="size-4" /></Button>
        <Button variant="outline" size="icon-sm" aria-label={`다음 ${label}`} aria-controls={id} disabled={!edges.next} onClick={() => move(1)}><ChevronRight aria-hidden="true" className="size-4" /></Button>
        </div>}
      </div>}
    </div>
  )
}
