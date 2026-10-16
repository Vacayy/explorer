import { test } from 'node:test'
import assert from 'node:assert/strict'
import { append, normalize, pack } from '../src/components/widgets/layout.ts'

const SIZES = { a: { w: 12, h: 1, minW: 6, minH: 1 }, b: { w: 6, h: 4, minW: 4, minH: 3 }, c: { w: 3, h: 3, minW: 3, minH: 2 } }

test('presets pack left to right and wrap rows', () => {
  const l = pack(['a', 'b', 'b', 'c', 'c', 'c', 'c'], SIZES)
  assert.deepEqual(l.map(e => [e.widget, e.x, e.y]), [['a', 0, 0], ['b', 0, 1], ['b', 6, 1], ['c', 0, 5], ['c', 3, 5], ['c', 6, 5], ['c', 9, 5]])
  assert.equal(new Set(l.map(e => e.i)).size, l.length)
})

test('append fills the first free spot, else goes below, with a fresh id', () => {
  const l = append(pack(['b', 'c'], SIZES), 'c', SIZES)   // b(0..5) c(6..8) → 9..11 비어 있음
  const last = l.at(-1)
  assert.deepEqual([last.x, last.y], [9, 0])
  const full = append(pack(['a'], SIZES), 'b', SIZES)      // a가 한 줄을 다 차지 → 아래로
  assert.deepEqual([full.at(-1).x, full.at(-1).y], [0, 1])
  assert.equal(new Set(l.map(e => e.i)).size, l.length)   // 기존 id와 겹치지 않는다
})

test('normalize drops unknown widgets and duplicates, clamps sizes', () => {
  const l = normalize([
    { i: 'x#0', widget: 'gone', x: 0, y: 0, w: 4, h: 4 },
    { i: 'b#0', widget: 'b', x: 10, y: 0, w: 2, h: 1 },
    { i: 'b#0', widget: 'b', x: 0, y: 5, w: 6, h: 4 },
  ], SIZES)
  assert.deepEqual(l, [{ i: 'b#0', widget: 'b', x: 8, y: 0, w: 4, h: 3 }])
})
