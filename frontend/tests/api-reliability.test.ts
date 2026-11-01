import { afterEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders, CanceledError } from 'axios'
import { z } from 'zod'
import api, { REQUEST_TIMEOUT } from '../src/api/client'
import { ApiError, shouldRetry, toApiError } from '../src/api/errors'
import { boardSchema, feedSchema, parseResponse, validateResponse } from '../src/api/contracts'
import { apiQuery, createQueryClient, getJson, postJson } from '../src/api/query'

const adapter = api.defaults.adapter
afterEach(() => { api.defaults.adapter = adapter; vi.restoreAllMocks() })
const respond = (data: unknown, status = 200, contentType = 'application/json') => {
  api.defaults.adapter = async config => ({ data, status, statusText: 'OK', config, headers: new AxiosHeaders({ 'content-type': contentType }) })
}

describe('transport and normalization', () => {
  it('uses a finite timeout and accepts successful 201 and 204 responses', async () => {
    expect(api.defaults.timeout).toBe(REQUEST_TIMEOUT)
    respond({ id: 1 }, 201)
    await expect(postJson('/created', {})).resolves.toEqual({ id: 1 })
    respond('', 204)
    await expect(api.delete('/deleted')).resolves.toHaveProperty('status', 204)
  })
  it.each([['ERR_NETWORK', 'network'], ['ECONNABORTED', 'timeout'], ['ETIMEDOUT', 'timeout']])('normalizes %s for direct and wrapped requests', async (code, kind) => {
    api.defaults.adapter = async () => { throw new AxiosError('raw diagnostic', code) }
    await expect(api.get('/test')).rejects.toMatchObject({ kind })
    await expect(getJson('/test')).rejects.toMatchObject({ kind })
  })
  it.each([400, 401, 403, 404, 422, 429, 500, 503])('preserves HTTP status %s and safe messages', async status => {
    api.defaults.adapter = async config => { throw new AxiosError('raw', 'ERR_BAD_RESPONSE', config, undefined, { status, data: { detail: [{ msg: '필수값 누락' }, null, { msg: {} }] }, statusText: '', headers: new AxiosHeaders(), config }) }
    await expect(api.get('/test')).rejects.toMatchObject({ status, kind: 'http' })
    try { await getJson('/test') } catch (error) { expect(typeof (error as Error).message).toBe('string') }
  })
  it('preserves cancellation rather than reporting a network failure', async () => {
    const controller = new AbortController()
    controller.abort()
    await expect(getJson('/test', undefined, { signal: controller.signal })).rejects.toBeInstanceOf(CanceledError)
    expect(shouldRetry(0, new CanceledError())).toBe(false)
  })
  it('rejects HTML/malformed JSON even with HTTP 200', async () => {
    respond('<html>proxy</html>', 200, 'text/html')
    await expect(getJson('/test')).rejects.toMatchObject({ kind: 'schema' })
    respond('{broken')
    await expect(getJson('/test')).rejects.toMatchObject({ kind: 'schema' })
  })
  it('does not wrap normalized errors or retry permanent failures', () => {
    const schemaError = new ApiError('invalid', undefined, { kind: 'schema' })
    expect(toApiError(schemaError)).toBe(schemaError)
    expect(shouldRetry(0, schemaError)).toBe(false)
    expect(shouldRetry(0, new ApiError('missing', 404))).toBe(false)
    expect(shouldRetry(0, new ApiError('busy', 503))).toBe(true)
    expect(shouldRetry(1, new ApiError('busy', 503))).toBe(false)
  })
})

describe('runtime contracts', () => {
  it('distinguishes empty data from malformed data and validates nested types', () => {
    expect(validateResponse('get', '/api/dashboard/boards', [])).toEqual([])
    expect(() => validateResponse('get', '/api/dashboard/boards', {})).toThrow(ApiError)
    expect(() => parseResponse(boardSchema, { id: 1, label: 'home', sort: 0, updated_at: '', items: [{ i: '1', widget: 'a', x: 0, y: 0, w: '12', h: 1 }] })).toThrow(ApiError)
    expect(() => parseResponse(feedSchema, { items: [], total: 0, page: 1, size: 0, as_of: '' })).toThrow(ApiError)
    expect(() => validateResponse('get', '/api/companies/005930', null)).toThrow(ApiError)
  })
  it('retains new server fields without coercing known fields', () => {
    const value = { corp_code: '1', corp_name: 'a', stock_code: null, market: null, sector: null, extra: true }
    expect(validateResponse('get', 'http://localhost:8000/api/companies/1?q=x', value)).toEqual(value)
    expect(() => validateResponse('get', '/api/companies/1', { ...value, corp_name: 123 })).toThrow(ApiError)
  })
  it('supports explicit nullable schemas and exposes diagnostic paths', async () => {
    respond(null)
    await expect(getJson('/optional', undefined, { schema: z.string().nullable() })).resolves.toBeNull()
    respond({ total: 'wrong' })
    try { await getJson('/optional', undefined, { schema: z.object({ total: z.number() }) }) } catch (error) {
      expect(error).toMatchObject({ kind: 'schema', issues: [{ path: ['total'] }] })
    }
  })
  it('rejects invalid data before cache insertion and retains good data after failed refresh', async () => {
    const onError = vi.fn()
    const client = createQueryClient(onError)
    const query = apiQuery({ key: ['boards'], url: '/api/dashboard/boards', staleTime: 0 })
    respond([])
    await client.fetchQuery(query)
    respond({ items: [] })
    await expect(client.fetchQuery(query)).rejects.toMatchObject({ kind: 'schema' })
    expect(client.getQueryData(['boards'])).toEqual([])
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][1]).toEqual({ background: true })
    client.clear()
  })
})

it('validates collection preview and start responses separately, including Axios params', async () => {
  const preview = { dry_run: true, budget: 22, would_request: 2, skipped_cache: 0, planned: ['A', 'B'], over_budget: 0 }
  respond(preview)
  await expect(api.post('/api/spine/transcript/collect', null, { params: { dry_run: true } })).resolves.toMatchObject({ data: preview })
  await expect(api.post('/api/spine/transcript/collect')).rejects.toMatchObject({ kind: 'schema' })
  respond({ started: true, budget: 22, tickers: null })
  await expect(api.post('/api/spine/transcript/collect')).resolves.toMatchObject({ data: { started: true } })
  await expect(api.post('/api/spine/transcript/collect?dry_run=1')).rejects.toMatchObject({ kind: 'schema' })
  respond({ ...preview, planned: [12] })
  await expect(api.post('/api/spine/transcript/collect?dry_run=1')).rejects.toMatchObject({ kind: 'schema' })
})
