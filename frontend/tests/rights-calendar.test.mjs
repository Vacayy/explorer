import { test } from 'node:test'
import assert from 'node:assert/strict'
import { kstToday, upcomingRightsEvents } from '../src/components/widgets/rightsCalendar.ts'

const row = (over) => ({ corp_name: 'x', my_group: null, date_ex_rights: null, date_sub_start: null, date_public_start: null,
  date_rights_listing_end: null, date_payment: null, date_new_listing: null, ...over })

test('KST today rolls over at 15:00 UTC', () => {
  assert.equal(kstToday(new Date('2026-10-16T14:59:00Z')), '2026-10-16')
  assert.equal(kstToday(new Date('2026-10-16T15:00:00Z')), '2026-10-17')
})

test('only events within the window, sorted by D-day then my stocks first', () => {
  const rows = [
    row({ corp_name: 'A', date_ex_rights: '2026-10-19', date_new_listing: '2026-12-17' }),
    row({ corp_name: 'B', my_group: '보유', date_new_listing: '2026-10-19' }),
    row({ corp_name: 'C', date_payment: '2026-10-15', date_sub_start: '2026-10-16' }),
  ]
  const ev = upcomingRightsEvents(rows, '2026-10-16', 7)
  assert.deepEqual(ev.map(e => [e.row.corp_name, e.label, e.dday]), [['C', '구주주 청약', 0], ['B', '신주 상장', 3], ['A', '권리락', 3]])
})
