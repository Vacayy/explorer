import { test } from 'node:test'
import assert from 'node:assert/strict'
import { aiCoverageLabel, groupDirectory, isSystemChannel } from '../src/lib/canvas.ts'

const ch = (id, platform, unread = 0) => ({ id, name: id, platform, count: 1, unread, latest_at: null, preview: '' })

test('human sources come first, system items fold into Explorer kinds', () => {
  const d = groupDirectory([
    ch('company:1', 'system', 3), ch('telegram:a', 'telegram', 5), ch('transcript:9', 'system', 1),
    ch('company:2', 'system', 0), ch('blog:x', 'blog', 2), ch('narrative:all', 'system', 4),
  ])
  assert.deepEqual(d.human.map(i => i.id), ['telegram:a', 'blog:x'])
  assert.deepEqual(d.explorer.groups.map(g => [g.kind, g.items.length, g.unread]), [['company', 2, 3], ['transcript', 1, 1]])
  assert.deepEqual(d.explorer.singles.map(i => i.id), ['narrative:all'])
  assert.equal(d.explorer.count, 4)
  assert.equal(d.explorer.unread, 8)
})

test('empty kinds are omitted', () => {
  const d = groupDirectory([ch('youtube:u', 'youtube')])
  assert.deepEqual(d.explorer.groups, [])
  assert.equal(d.explorer.count, 0)
})

test('system channel detection by id prefix', () => {
  assert.equal(isSystemChannel('company:1643'), true)
  assert.equal(isSystemChannel('telegram:abc'), false)
})

test('AI coverage label is honest when the cap is reached', () => {
  const full = Array.from({ length: 30 }, (_, i) => `2026-10-${String(14 + (i % 3)).padStart(2, '0')} 0${i % 10}:00:00`)
  assert.equal(aiCoverageLabel(full, 30, 7), '최근 30건 · 10-14 00:00 이후')
  assert.equal(aiCoverageLabel(['2026-10-15 01:00:00', '2026-10-10 02:00:00'], 30, 7), '지난 7일 · 2건')
  assert.equal(aiCoverageLabel([], 30, 7), '지난 7일')
})
