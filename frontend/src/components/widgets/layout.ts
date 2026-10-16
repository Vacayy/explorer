/**
 * 대시보드 배치 — 순수 함수 (docs/specs/home-widgets.md §4·§5). React·DOM 의존 없음(테스트 대상).
 */
export const COLS = 12

export interface LayoutEntry { i: string; widget: string; x: number; y: number; w: number; h: number; params?: Record<string, unknown> }
export interface SizeSpec { w: number; h: number; minW: number; minH: number }

/** 위젯 목록을 12열 선반에 왼쪽→오른쪽, 위→아래로 채운다(프리셋·추가용) */
export function pack(widgets: string[], sizes: Record<string, SizeSpec>): LayoutEntry[] {
  const out: LayoutEntry[] = []
  let x = 0, y = 0, rowH = 0
  widgets.forEach((widget, n) => {
    const s = sizes[widget]
    if (!s) return
    if (x + s.w > COLS) { x = 0; y += rowH; rowH = 0 }
    out.push({ i: `${widget}#${n}`, widget, x, y, w: s.w, h: s.h })
    x += s.w; rowH = Math.max(rowH, s.h)
  })
  return out
}

/** 맨 아래에 하나 붙인다 */
export function append(layout: LayoutEntry[], widget: string, sizes: Record<string, SizeSpec>): LayoutEntry[] {
  const s = sizes[widget]
  if (!s) return layout
  const bottom = layout.reduce((m, e) => Math.max(m, e.y + e.h), 0)
  let n = 0
  while (layout.some(e => e.i === `${widget}#${n}`)) n++
  return [...layout, { i: `${widget}#${n}`, widget, x: 0, y: bottom, w: s.w, h: s.h }]
}

/** 저장본·편집 결과 정리 — 모르는 위젯 제거, 중복 id 제거, 크기 하한·열 폭 상한 */
export function normalize(layout: LayoutEntry[], sizes: Record<string, SizeSpec>): LayoutEntry[] {
  const seen = new Set<string>()
  const out: LayoutEntry[] = []
  for (const e of layout) {
    const s = sizes[e.widget]
    if (!s || seen.has(e.i)) continue
    seen.add(e.i)
    const w = Math.min(COLS, Math.max(s.minW, Math.round(e.w)))
    const h = Math.max(s.minH, Math.round(e.h))
    out.push({ ...e, w, h, x: Math.max(0, Math.min(COLS - w, Math.round(e.x))), y: Math.max(0, Math.round(e.y)) })
  }
  return out
}
