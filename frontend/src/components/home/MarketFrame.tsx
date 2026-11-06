import type { ReactNode } from "react"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { BAND, type BandSize } from "@/components/shared/Bounded"
import { cn } from "@/lib/utils"

/**
 * 홈 › 한국·미국 시장 공통 틀(ia-redesign §4.2·4.3, 시안 Home-KR·US) — 12칸 격자의 띠. 칸끼리 테두리를 겹친다(시안 .wg).
 * 좁은 화면(<768)은 한 줄로 쌓는다. 칸 = [span, 내용].
 */
export function Band({ label, cells, className }: { label: string; cells: [number, ReactNode][]; className?: string }) {
  return <section aria-label={label} className={cn("grid grid-cols-1 pr-px pb-px md:grid-cols-12 [&>*]:-mr-px [&>*]:-mb-px [&>*]:min-w-0", className)}>
    {cells.map(([span, node], i) => <div key={i} className={cn("flex flex-col max-md:!col-span-1", SPAN[span])}>{node}</div>)}
  </section>
}
const SPAN: Record<number, string> = { 4: "md:col-span-4", 5: "md:col-span-5", 6: "md:col-span-6", 7: "md:col-span-7", 8: "md:col-span-8", 12: "md:col-span-12" }

/** 띠의 칸 — 시안 section: 고정 높이 · 안쪽 16/18 · 세로 간격 12 · 넘침은 안쪽 스크롤 영역(FillArea)이 맡는다 */
export function MarketCard({ band, children, className, label, id }: { band: BandSize; children: ReactNode; className?: string; label?: string; id?: string }) {
  return <Card id={id} data-home-section={label} data-band={band}
    className={cn("flex min-h-0 min-w-0 scroll-mt-4 flex-col gap-3 overflow-hidden rounded-[var(--radius-card)] px-[18px] py-4 shadow-none", BAND[band], className)}>
    {children}
  </Card>
}

/** AI 요약 표시 줄(시안 ai_line) — 보라 반짝이 + 11.5 */
export function AiLine({ children }: { children: ReactNode }) {
  return <p className="flex shrink-0 items-center gap-1.5 text-[11.5px] text-hyp">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3l1.8 4.6L18 9.4l-4.2 1.8L12 16l-1.8-4.8L6 9.4l4.2-1.8z" /><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
    </svg>{children}
  </p>
}

/** 시안 세그먼트(칩 바탕 3 · 버튼 28 · 12.5/500) — 공식 ToggleGroup. 띠 머리 오른쪽·지수 전환에 쓴다 */
export function Seg({ label, value, items, onChange, className }: { label: string; value: string; items: { key: string; label: string; disabled?: boolean }[]; onChange: (v: string) => void; className?: string }) {
  return <ToggleGroup type="single" aria-label={label} value={value} onValueChange={v => v && onChange(v)} className={className}>
    {items.map(t => <ToggleGroupItem key={t.key} value={t.key} disabled={t.disabled} className="h-7 min-w-0 px-3 text-[12.5px] font-medium">{t.label}</ToggleGroupItem>)}
  </ToggleGroup>
}

/** 칸 안 목록 뼈대 — 남은 높이를 채운다(최종 높이와 같게) */
export function FillSkeleton({ rows = 8, label = "불러오는 중" }: { rows?: number; label?: string }) {
  return <div role="status" aria-label={label} aria-busy="true" className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
    {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-7 w-full shrink-0" />)}
  </div>
}

/** 칸 안 한 줄 상태(빈·첫 회차 전) — 목록 자리에만 */
export function FillNote({ children }: { children: ReactNode }) {
  return <p role="status" className="min-h-0 flex-1 text-sm text-ink-3">{children}</p>
}

/** 판정 4칸(시안 kpis) — 이름 11.5 · 값 Geist 20 + 보조 12 */
export function KpiStrip({ items }: { items: { label: string; value: string; of?: string }[] }) {
  return <div className="grid shrink-0 grid-cols-4 pr-px pb-px max-sm:grid-cols-2 [&>*]:-mr-px [&>*]:-mb-px">
    {items.map(k => <div key={k.label} className="flex min-w-0 flex-col gap-0.5 border px-3 py-2.5">
      <span className="truncate text-[11.5px] text-ink-3">{k.label}</span>
      <span className="truncate font-display text-xl tabular-nums">{k.value}{k.of && <span className="ml-1 text-xs text-ink-3">{k.of}</span>}</span>
    </div>)}
  </div>
}
