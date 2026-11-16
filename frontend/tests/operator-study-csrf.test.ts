import { beforeEach, expect, it, vi } from 'vitest'

vi.mock('@/lib/accessMode', () => ({ PUBLIC_ACCESS: true }))
vi.mock('@/api/contracts', () => ({ validateResponse: async (_method: string, _url: string, data: unknown) => data }))
vi.mock('@/api/telemetry', () => ({ reportApiError: () => {} }))

const { default: api } = await import('@/api/client')
let role = 'operator'
let seen: { url: string; csrf: string | undefined }[] = []

beforeEach(() => {
  role = 'operator'
  seen = []
  api.defaults.adapter = async config => {
    seen.push({ url: config.url ?? '', csrf: config.headers.get('X-CSRF-Token') as string | undefined })
    const data = config.url === '/api/auth/session'
      ? { authenticated: true, user: { id: 'fixture', role }, csrf_token: 'csrf-fixture' }
      : { ok: true }
    return { data, status: 200, statusText: 'OK', headers: { 'content-type': 'application/json' }, config }
  }
})

it('adds the current operator CSRF token to study writes', async () => {
  await api.post('/api/spine/study-projects', { title: 'fixture' })
  expect(seen).toEqual([
    { url: '/api/auth/session', csrf: undefined },
    { url: '/api/spine/study-projects', csrf: 'csrf-fixture' },
  ])
})

it('blocks a non-operator before sending a legacy study write', async () => {
  role = 'member'
  await expect(api.post('/api/spine/studies/1/annotations', {})).rejects.toThrow()
  expect(seen.map(x => x.url)).toEqual(['/api/auth/session'])
})

it('protects legacy portfolio writes with the operator session', async () => {
  await api.post('/api/portfolio/transactions', {})
  expect(seen.map(x => x.csrf)).toEqual([undefined, 'csrf-fixture'])
  role = 'member'
  seen = []
  await expect(api.delete('/api/portfolio/transactions/1')).rejects.toThrow()
  expect(seen.map(x => x.url)).toEqual(['/api/auth/session'])
})
