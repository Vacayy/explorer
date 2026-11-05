import { describe, expect, it } from 'vitest'
import { findResponseContract, validateOpenApiResponse } from '../src/api/openapi'
import { validateResponse } from '../src/api/contracts'
import routes from '../src/api/generated/routes.json'
import unmodeled from '../src/api/generated/unmodeled.json'
import unresolved from '../src/api/generated/unresolved-types.json'

it('has no unresolved frontend response types and validates the main read domains', () => {
  expect(unresolved).toEqual([])
  expect(routes.length).toBeGreaterThanOrEqual(272)
  for (const path of ['/api/spine/saved', '/api/portfolio', '/api/financials/005930', '/api/stock-prices/005930',
    '/api/spine/groups/default-watch', '/api/spine/sources/youtube', '/api/spine/search', '/api/spine/search/today',
    '/api/spine/person/followed', '/api/spine/doc/1', '/api/analysis/discovery/cases', '/api/analysis/strategies',
    '/api/spine/transcript/collect/status', '/api/spine/transcript/momentum']) {
    expect(findResponseContract('get', path), path).toBeDefined()
  }
})

it('explicitly accounts for the remaining unused JSON reads and non-JSON streams/artifacts', () => {
  expect(unmodeled.filter(route => route.method === 'get').map(route => route.path).sort()).toEqual([
    '/api/analysis/runs/{run_id}/artifacts/{artifact_id}', '/api/analysis/runs/{run_id}/events',
    '/api/compare', '/api/consensus/{stock_code}', '/api/health', '/api/signals', '/api/spine/conversations/{conversation_id}/stream',
    '/api/spine/groups/{group_id}/evaluations', '/api/spine/trade/{hs_code}/metrics',
  ].sort())
})

it('resolves static routes before parameter routes and excludes event streams', () => {
  expect(findResponseContract('get', '/api/spine/search/today')).not.toEqual(findResponseContract('get', '/api/spine/search'))
  expect(findResponseContract('get', '/api/spine/transcript/collect/status')).toBeDefined()
  expect(findResponseContract('get', '/api/analysis/runs/id/events')).toBeUndefined()
  expect(findResponseContract('delete', '/api/analysis/runs/id')).toBeUndefined()
})

describe('generated model and consumer schemas', () => {
  it('preserves successful empty lists and rejects invalid top-level types', async () => {
    await expect(validateResponse('get', '/api/portfolio/principles', [])).resolves.toEqual([])
    await expect(validateResponse('get', '/api/portfolio/principles', {})).rejects.toMatchObject({ kind: 'schema' })
    await expect(validateResponse('get', '/api/spine/groups', { items: 'invalid' })).rejects.toMatchObject({ kind: 'schema' })
  })
  it('retains unknown fields while enforcing consumer fields, nested arrays and types', async () => {
    const catalog = { version: '1', items: [], future: { enabled: true } }
    await expect(validateResponse('get', '/api/analysis/strategies', catalog)).resolves.toBe(catalog)
    await expect(validateResponse('get', '/api/analysis/strategies', { ...catalog, version: 1 })).rejects.toMatchObject({ kind: 'schema' })
    await expect(validateResponse('get', '/api/analysis/strategies', { ...catalog, items: [{}] })).rejects.toMatchObject({ kind: 'schema' })
  })
  it('validates query-string URLs and reports diagnostic paths without payloads', async () => {
    await expect(validateResponse('get', 'http://localhost:8000/api/analysis/strategies?fresh=1', { version: '1', items: 12 }))
      .rejects.toMatchObject({ issues: [{ path: ['items'] }] })
  })
  it('does not infer a contract for unused or non-JSON endpoints', async () => {
    await expect(validateOpenApiResponse('get', '/api/health', { status: 'ok' })).resolves.toEqual({ status: 'ok' })
  })
})

it('rejects malformed mutation results before callers use navigation IDs, revisions or added documents', async () => {
  for (const [method, path, valid, invalid] of [
    ['post', '/api/spine/studies', { id: 1 }, { id: 'wrong' }],
    ['post', '/api/spine/study-projects/1/documents', { study_ids: [1, 2] }, { study_ids: {} }],
    ['post', '/api/spine/study-projects/1/clips', { study_ids: [] }, {}],
    ['patch', '/api/spine/study-projects/1', { revision: 2 }, { revision: null }],
    ['post', '/api/spine/questions/propose', { proposed: 0 }, { proposed: '0' }],
  ] as const) {
    await expect(validateResponse(method, path, valid)).resolves.toEqual(valid)
    await expect(validateResponse(method, path, invalid)).rejects.toMatchObject({ kind: 'schema' })
  }
})
