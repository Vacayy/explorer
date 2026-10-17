import { test } from 'node:test'
import assert from 'node:assert/strict'
import { aimAt, fromEntries, move, place, resizeWidth, tidy, toEntries, widths } from '../src/components/widgets/rows.ts'

const H = { a: 4, b: 15, c: 15, d: 12, e: 12, f: 12 }
const heightOf = id => H[id] ?? 10

test('rows fill the full width; custom spans only when they add to 12', () => {
  assert.deepEqual(widths(['a', 'b', 'c'], {}), [4, 4, 4])
  assert.deepEqual(widths(['a', 'b'], { a: 8, b: 4 }), [8, 4])
  assert.deepEqual(widths(['a', 'b'], { a: 8, b: 5 }), [6, 6])
})

test('place stacks rows, row height = tallest, east handle only between neighbours', () => {
  const p = place([['a'], ['b', 'c'], ['d', 'e', 'f']], heightOf, {})
  assert.deepEqual(p.map(x => [x.i, x.x, x.y, x.w, x.h]), [['a', 0, 0, 12, 4], ['b', 0, 4, 6, 15], ['c', 6, 4, 6, 15], ['d', 0, 19, 4, 12], ['e', 4, 19, 4, 12], ['f', 8, 19, 4, 12]])
  assert.deepEqual(p.find(x => x.i === 'c').resizeHandles, ['s'])
  assert.deepEqual(p.find(x => x.i === 'b').resizeHandles, ['s', 'e'])
})

test('move into a row, into a full row (last spills down), or as a new row', () => {
  assert.deepEqual(move([['a'], ['b', 'c']], 'a', { kind: 'into', row: 1, index: 1 }), [['b', 'a', 'c']])
  assert.deepEqual(move([['a'], ['d', 'e', 'f']], 'a', { kind: 'into', row: 1, index: 0 }), [['a', 'd', 'e'], ['f']])
  assert.deepEqual(move([['a', 'b']], 'b', { kind: 'newRow', at: 0 }), [['b'], ['a']])
})

test('aim: row edges make a new row, the middle inserts between widgets', () => {
  const rows = [['a'], ['b', 'c']]
  assert.deepEqual(aimAt(rows, heightOf, 'a', 2, 5), { kind: 'newRow', at: 1 })        // b·c 줄의 위 가장자리
  assert.deepEqual(aimAt(rows, heightOf, 'a', 10.5, 12), { kind: 'into', row: 1, index: 2 }) // 오른쪽 끝(두 번째 위젯 가운데 9보다 오른쪽)
  assert.deepEqual(aimAt(rows, heightOf, 'a', 1, 12), { kind: 'into', row: 1, index: 0 })
  assert.deepEqual(aimAt(rows, heightOf, 'a', 1, 99), { kind: 'newRow', at: 2 })
})

test('resizing a boundary trades width with the right neighbours and wraps them when squeezed', () => {
  const r1 = resizeWidth([['d', 'e', 'f']], 'd', 6, {})
  assert.deepEqual(r1.rows, [['d', 'e', 'f']])
  assert.deepEqual([r1.spans.d, r1.spans.e, r1.spans.f], [6, 3, 3])
  const r2 = resizeWidth([['d', 'e', 'f']], 'd', 8, {})             // e·f 최소 3+3 > 4 → f가 아랫줄로
  assert.deepEqual(r2.rows, [['d', 'e'], ['f']])
  assert.deepEqual([r2.spans.d, r2.spans.e], [8, 4])
})

test('tidy drops unknown and duplicate ids and appends missing ones', () => {
  assert.deepEqual(tidy([['a', 'x'], ['a', 'b']], ['a', 'b', 'c']), [['a'], ['b'], ['c']])
})

test('entries round-trip keeps rows, spans and chosen heights', () => {
  const rows = [['a'], ['b', 'c']], spans = { b: 8, c: 4 }, heights = { a: 4, b: 15, c: 9 }
  const e = toEntries(rows, spans, heights, i => `w.${i}`, () => 10)
  assert.deepEqual(e.map(x => [x.i, x.x, x.y, x.w, x.h]), [['a', 0, 0, 12, 4], ['b', 0, 4, 8, 15], ['c', 8, 4, 4, 9]])
  assert.deepEqual(fromEntries(e), { rows, spans: { a: 12, b: 8, c: 4 }, heights })
})
