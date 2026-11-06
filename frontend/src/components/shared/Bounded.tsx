import { useEffect, useLayoutEffect, useRef, type ComponentProps, type ReactNode } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

/**
 * 높이 상한 눈금 (docs/DESIGN_SYSTEM.md '높이 상한과 넘침') — 내용이 길어도 카드가 늘지 않게 본문 영역에 거는 최대 높이.
 * 넓은 화면 px 상한과 창 높이 비율 중 작은 쪽, 좁은 화면(<640)은 같은 눈금을 줄인 값.
 *   sm   — 반 폭 블록 안 짧은 목록(칩·행 6~8개)
 *   md   — 블록 본문 기본(목록·표·AI 글)
 *   lg   — 전체 폭 긴 표·전문
 * Tailwind가 클래스를 읽을 수 있게 문자열을 통째로 둔다.
 */
export const BOUND = {
  sm: "max-h-[min(320px,45vh)] max-sm:max-h-[min(280px,45vh)]",
  md: "max-h-[min(480px,60vh)] max-sm:max-h-[min(400px,55vh)]",
  lg: "max-h-[min(640px,70vh)] max-sm:max-h-[min(480px,60vh)]",
} as const
export type BoundSize = keyof typeof BOUND
/** 같은 눈금의 고정 높이 — 필터·정렬·탭으로 행 수가 바뀌는 목록은 상한이 아니라 높이 자체를 고정한다(전환해도 카드가 그대로) */
export const BOUND_FIXED = {
  sm: "h-[min(320px,45vh)] max-sm:h-[min(280px,45vh)]",
  md: "h-[min(480px,60vh)] max-sm:h-[min(400px,55vh)]",
  lg: "h-[min(640px,70vh)] max-sm:h-[min(480px,60vh)]",
} as const satisfies Record<BoundSize, string>

/**
 * 홈 › 한국·미국 시장 띠 높이(ia-redesign §4.2·4.3, 시안 Home-KR·US) — 같은 줄의 칸은 같은 높이로 고정하고 넘치는 목록은 칸 안에서 푼다.
 * 넓은 화면(md+)은 시안 값, 좁은 화면은 줄인 값(②·③ 420 · ④·⑤ 400). ①은 좁은 화면에서 차트 220 + 지표 2×2라 내용 높이.
 */
export const BAND = {
  index: "md:h-[380px]",
  summary: "h-[420px] md:h-[440px]",
  stocks: "h-[420px] md:h-[500px]",
  events: "h-[400px] md:h-[460px]",
  local: "h-[400px]",
  /** 산업 › 섹터 지도·섹터 화면(ia-redesign §4.35, 시안 Industry-Map·Sector-*) — 460 지도·순위 / 400 대표지수 / 560 개괄·자료 / 720 개요 Peer 그룹 / 760 Peer 탭 */
  sectorMap: "h-[420px] md:h-[460px]",
  sectorChart: "h-[360px] md:h-[400px]",
  sectorText: "h-[480px] md:h-[560px]",
  sectorPeers: "h-[560px] md:h-[760px]",
  /** 섹터 개요의 Peer 그룹 칸 — Peer 탭과 같은 컴포넌트를 조금 낮게 */
  sectorPeerBlock: "h-[560px] md:h-[720px]",
} as const
export type BandSize = keyof typeof BAND

/**
 * 고정 높이 칸의 남은 높이를 채우는 스크롤 영역 — 칸(flex 세로) 안에서 머리·바닥 줄을 뺀 자리. 공식 ScrollArea 위 조합.
 * 스크롤 막대 자리만큼 오른쪽으로 내어 쓴다(시안 .sc: margin-right −10 · padding-right 10).
 */
export function FillArea({ className, viewportClassName, children, ...props }: ComponentProps<typeof ScrollArea>) {
  return <ScrollArea data-bounded="fill" className={cn("-mr-2.5 min-h-0 flex-1", className)} viewportClassName={cn("pr-2.5 [&>div]:!block", viewportClassName)} {...props}>
    {children}
  </ScrollArea>
}

/**
 * 상한 안에서만 스크롤하는 본문 영역 — 공식 shadcn ScrollArea(Radix) 위 조합.
 * 상한은 실제 스크롤 상자(viewport)에 건다(Root에만 걸면 스크롤이 안 잡힌다, ui/scroll-area 주석).
 * Radix 안쪽 상자의 display:table을 block으로 — 말줄임(truncate)이 폭을 넘기지 않게(shared/ProposalPanel과 같은 처리).
 */
export function BoundedArea({ size = "md", fixed, className, viewportClassName, children, ...props }: ComponentProps<typeof ScrollArea> & { size?: BoundSize
  /** 상한 대신 그 높이로 고정(행 수가 바뀌는 목록) */
  fixed?: boolean }) {
  return <ScrollArea data-bounded={size} className={cn("min-h-0", className)} viewportClassName={cn(fixed ? BOUND_FIXED[size] : BOUND[size], "[&>div]:!block", viewportClassName)} {...props}>
    {children}
  </ScrollArea>
}

/**
 * 제자리 펼침 — '더 보기'·행 펼침을 눌러도 펼치기 직전 높이를 그대로 고정하고, 늘어난 내용은 그 안에서 스크롤한다.
 * 카드·아래 블록이 움직이지 않는다. 접힌 동안은 size 눈금(있으면)을 상한으로 그린다.
 * 같은 ScrollArea를 계속 쓰므로 펼쳐도 스크롤 위치가 유지된다.
 *   <InPlaceMore open={more}>{rows.slice(0, more ? undefined : 5)}</InPlaceMore>
 *   <InPlaceMore open={openRow != null} size="md">{rows}</InPlaceMore>   // 행 펼침 목록
 */
export function InPlaceMore({ open, size, children, className }: { open: boolean; size?: BoundSize; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const closed = useRef(0)
  useLayoutEffect(() => { if (!open && ref.current) closed.current = ref.current.offsetHeight })
  // 접는 애니메이션(Radix Presence)이 끝나 내용이 빠진 뒤의 높이도 따라간다 — 렌더 시점 측정만으로는 펼친 높이가 남는다
  useEffect(() => {
    const el = ref.current
    if (open || !el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(() => { closed.current = el.offsetHeight })
    ro.observe(el)
    return () => ro.disconnect()
  }, [open])
  const lock = open && closed.current > 0
  return <ScrollArea ref={ref} data-bounded={size ?? "in-place"} className={cn("min-h-0", className)}
    viewportClassName={cn(size && !lock && BOUND[size], "[&>div]:!block")} viewportStyle={lock ? { height: closed.current } : undefined}>
    {children}
  </ScrollArea>
}
