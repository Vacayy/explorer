/**
 * 대시보드 줄 배치 — 순수 함수 (docs/specs/home-widgets.md §1). React·DOM 의존 없음(노드 테스트 대상).
 *
 * 보드 = 위에서 아래로 쌓인 줄. 한 줄에 위젯 1~3개가 폭을 나눠 꽉 채운다(빈틈 없음).
 * - 끌어 놓기: 줄 안(왼쪽·사이·오른쪽)이면 그 줄에 끼어들고, 줄의 위·아래 가장자리면 새 줄. 꽉 찬 줄에 끼우면 맨 끝이 아랫줄로.
 * - 높이: 위젯마다 정한 높이를 기억하고, 줄 높이는 그 줄의 가장 큰 값(바닥선이 맞는다).
 * - 폭: 위젯 사이 경계를 끌면 오른쪽 이웃들과 폭을 주고받는다(12칸 기준 span으로 기억). 이웃이 최소 폭보다 눌리면 맨 끝부터 아랫줄로.
 * react-grid-layout에는 정렬기(compactor)로 이 모델의 좌표를 그대로 돌려준다.
 */
export const COLS = 12
export const MAX_IN_ROW = 3
export const MIN_SPAN = 3

export type Rows = string[][]
export type Spans = Record<string, number>
export type Heights = Record<string, number>
export interface Placed { i: string; x: number; y: number; w: number; h: number; resizeHandles: ("s" | "e")[] }
export type Target = { kind: "into"; row: number; index: number } | { kind: "newRow"; at: number }

/** 줄의 폭(칸) — 줄 위젯이 모두 span을 갖고 합이 12면 그 비율, 아니면 똑같이 */
export function widths(row: readonly string[], spans: Spans): number[] {
  const s = row.map(id => spans[id])
  if (s.every(v => typeof v === "number" && v > 0) && s.reduce((a, b) => a + b, 0) === COLS) return s as number[]
  const base = Math.floor(COLS / row.length)
  return row.map((_, k) => (k === row.length - 1 ? COLS - base * (row.length - 1) : base))
}

/** 줄 → 격자 좌표 */
export function place(rows: Rows, heightOf: (id: string) => number, spans: Spans, resizing?: string): Placed[] {
  const out: Placed[] = []
  let y = 0
  for (const row of rows) {
    const h = Math.max(...row.map(heightOf))
    const ws = widths(row, spans)
    let x = 0
    row.forEach((id, k) => {
      // 줄의 마지막이 아니면 오른쪽 경계로 이웃과 폭을 주고받는다. 조절 중인 위젯은 손잡이를 지킨다(끊기지 않게)
      const edge = k < row.length - 1 || id === resizing
      out.push({ i: id, x, y, w: ws[k], h, resizeHandles: edge ? ["s", "e"] : ["s"] })
      x += ws[k]
    })
    y += h
  }
  return out
}

/** 보드에 실제로 있는 위젯만, 중복 없이. 줄에 없는 위젯은 맨 아래 새 줄로 */
export function tidy(rows: Rows, ids: readonly string[]): Rows {
  const live = new Set(ids), seen = new Set<string>()
  const out = rows.map(r => r.filter(id => live.has(id) && !seen.has(id) && (seen.add(id), true)).slice(0, MAX_IN_ROW)).filter(r => r.length)
  for (const id of ids) if (!seen.has(id)) out.push([id])
  return out
}

/** id를 target으로 옮긴다(target은 옮기기 전 줄 번호 기준). 줄 구성이 바뀐 줄의 비율은 버린다 */
export function move(rows: Rows, id: string, target: Target): Rows {
  const next = rows.map(r => r.filter(x => x !== id))
  if (target.kind === "newRow") {
    next.splice(Math.max(0, Math.min(target.at, next.length)), 0, [id])
  } else {
    const row = next[target.row]
    if (!row) next.push([id])
    else {
      const spill = row.length >= MAX_IN_ROW ? row.pop() : undefined
      row.splice(Math.min(target.index, row.length), 0, id)
      if (spill) {
        const below = next[target.row + 1]
        if (below && below.length && below.length < MAX_IN_ROW) below.unshift(spill)
        else next.splice(target.row + 1, 0, [spill])
      }
    }
  }
  return next.filter(r => r.length)
}

/** 끄는 지점(격자 단위 gx·gy)이 가리키는 자리 */
export function aimAt(rows: Rows, heightOf: (id: string) => number, id: string, gx: number, gy: number): Target {
  if (gy < 0) return { kind: "newRow", at: 0 }
  let top = 0
  for (let r = 0; r < rows.length; r++) {
    const h = Math.max(...rows[r].map(heightOf)), bottom = top + h
    if (gy < bottom) {
      const edge = Math.min(3, h / 4)            // 줄 위·아래 가장자리 = 새 줄
      if (gy < top + edge) return { kind: "newRow", at: r }
      if (gy >= bottom - edge) return { kind: "newRow", at: r + 1 }
      const others = rows[r].filter(x => x !== id)
      const slot = COLS / Math.max(others.length, 1)
      return { kind: "into", row: r, index: others.filter((_, k) => (k + 0.5) * slot < gx).length }
    }
    top = bottom
  }
  return { kind: "newRow", at: rows.length }
}

/** 경계를 끌어 id의 폭을 span으로 — 오른쪽 이웃이 나머지를 비율대로 나눈다. 최소 폭보다 눌리면 맨 끝부터 아랫줄로 */
export function resizeWidth(rows: Rows, id: string, span: number, spans: Spans, minOf: (id: string) => number = () => MIN_SPAN):
  { rows: Rows; spans: Spans } {
  const r = rows.findIndex(row => row.includes(id))
  if (r < 0) return { rows, spans }
  const row = rows[r], k = row.indexOf(id), cur = widths(row, spans)
  const left = row.slice(0, k), leftSum = cur.slice(0, k).reduce((a, b) => a + b, 0)
  let right = row.slice(k + 1), rightCur = cur.slice(k + 1)
  const room = COLS - leftSum
  let mine = Math.min(Math.max(Math.round(span), minOf(id)), room)
  const spilled: string[] = []
  while (right.length && right.reduce((a, x) => a + minOf(x), 0) > room - mine) {
    spilled.unshift(right.at(-1)!); right = right.slice(0, -1); rightCur = rightCur.slice(0, -1)
  }
  if (!right.length) mine = room
  // 오른쪽 이웃: 원래 비율대로 나누되 각자 최소 폭 이상
  const total = room - mine, sumW = rightCur.reduce((a, b) => a + b, 0) || 1
  const rs = rightCur.map((w, j) => Math.max(minOf(right[j]), Math.floor((w / sumW) * total)))
  let rest = total - rs.reduce((a, b) => a + b, 0)
  for (let j = 0; rest > 0; j = (j + 1) % rs.length, rest--) rs[j]++
  for (let j = rs.length - 1; rest < 0 && j >= 0; j--) while (rest < 0 && rs[j] > minOf(right[j])) { rs[j]--; rest++ }

  const kept = [...left, id, ...right]
  const nextSpans: Spans = { ...spans }
  kept.forEach((x, j) => { nextSpans[x] = j < k ? cur[j] : j === k ? mine : rs[j - k - 1] })
  const next = rows.map(x => [...x])
  next[r] = kept
  if (spilled.length) {
    spilled.forEach(x => { delete nextSpans[x] })
    const below = next[r + 1]
    if (below && below.length + spilled.length <= MAX_IN_ROW) next[r + 1] = [...spilled, ...below]
    else next.splice(r + 1, 0, spilled)
  }
  return { rows: next, spans: nextSpans }
}

/* ── 저장 형식(서버 dashboard_layouts) ↔ 줄 모델 ── */
export interface Entry { i: string; widget: string; x: number; y: number; w: number; h: number; params?: Record<string, unknown> }

/** 저장본(y→x 정렬된 칸 좌표)을 줄·비율·정한 높이로 */
export function fromEntries(entries: Entry[]): { rows: Rows; spans: Spans; heights: Heights } {
  const byY = new Map<number, Entry[]>()
  for (const e of entries) byY.set(e.y, [...(byY.get(e.y) ?? []), e])
  const rows: Rows = [], spans: Spans = {}, heights: Heights = {}
  for (const y of [...byY.keys()].sort((a, b) => a - b)) {
    const row = byY.get(y)!.sort((a, b) => a.x - b.x).slice(0, MAX_IN_ROW)
    rows.push(row.map(e => e.i))
    row.forEach(e => { spans[e.i] = e.w; heights[e.i] = e.h })
  }
  return { rows, spans, heights }
}

/** 줄 모델을 저장본으로 — h는 '정한 높이'(줄 높이로 늘어난 값이 아니다) */
export function toEntries(rows: Rows, spans: Spans, heights: Heights, widgetOf: (i: string) => string, defaultH: (i: string) => number,
  params: Record<string, Record<string, unknown> | undefined> = {}): Entry[] {
  const out: Entry[] = []
  let y = 0
  for (const row of rows) {
    const ws = widths(row, spans)
    let x = 0
    row.forEach((i, k) => {
      out.push({ i, widget: widgetOf(i), x, y, w: ws[k], h: heights[i] ?? defaultH(i), ...(params[i] ? { params: params[i] } : {}) })
      x += ws[k]
    })
    y += Math.max(...row.map(i => heights[i] ?? defaultH(i)))
  }
  return out
}
