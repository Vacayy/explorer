import { test } from 'node:test'
import assert from 'node:assert/strict'
import { shiftDay, validDay, quarterRows } from '../src/utils/companyResearch.ts'

test('calendar lookback includes weekends and crosses year/leap boundaries', () => {
  assert.equal(shiftDay('2026-01-01', -6), '2025-12-26')
  assert.equal(shiftDay('2024-03-01', -1), '2024-02-29')
  assert.equal(shiftDay('2026-06-12', 0), '2026-06-12')
  assert.equal(validDay('2026-02-30'), false)
  assert.equal(validDay(''), false)
  assert.equal(validDay('2024-02-29'), true)
})
test('financial presentation preserves losses, zero and calendar gaps', () => {
  const rows = quarterRows({ periods: ['25.03','25.09','25.12','26.03'], rows: [
    { account_nm:'매출액', values:['1,000', '0', '500', null] },
    { account_nm:'영업이익', values:['-100', '0', '0', '4'] }
  ] })
  assert.deepEqual(rows.map(r=>r.period), ['25.03','25.06','25.09','25.12','26.03'])
  assert.equal(rows[0].margin, -10)
  assert.equal(rows[1].revenue, null)
  assert.equal(rows[2].margin, null)
  assert.equal(rows[3].margin, 0)
  assert.equal(rows[4].margin, null)
})
test('missing or nonnumeric financial amounts are never zero', () => {
  assert.deepEqual(quarterRows(), [])
  const rows = quarterRows({periods:['26.03'], rows:[{account_nm:'매출액',values:['-']}]})
  assert.equal(rows[0].revenue, null)
  assert.equal(rows[0].profit, null)
})
