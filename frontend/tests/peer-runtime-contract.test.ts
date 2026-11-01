import { expect, it } from 'vitest'
import { validateResponse } from '@/api/contracts'
import catalog from '@/data/peer-catalog.json'
import prices from '@/data/peer-prices.json'

const runtime = {
  catalog, prices, origin: 'collector', publishedAt: prices.collectedAt,
  baselineOn: '2026-11-01', lastAttempt: null, priceAgeDays: 2, snapshotAgeHours: 1,
  signalStatus: 'held', signalHoldReason: '기업행사 검증 미완료',
}

it('validates the Peer runtime contract including timezone timestamps and nullable attempts', async () => {
  await expect(validateResponse('get', '/api/peers/runtime', runtime)).resolves.toEqual(runtime)
  await expect(validateResponse('get', '/api/peers/runtime', { ...runtime, publishedAt: 'not-a-date' })).rejects.toThrow()
  await expect(validateResponse('get', '/api/peers/runtime', { ...runtime, signalStatus: 'enabled' })).rejects.toThrow()
  const missing = structuredClone(runtime)
  // @ts-expect-error Exercise required field enforcement, not TypeScript inference.
  delete missing.prices.session
  await expect(validateResponse('get', '/api/peers/runtime', missing)).rejects.toThrow()
})
