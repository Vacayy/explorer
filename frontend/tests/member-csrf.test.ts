// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import type { AxiosAdapter } from 'axios'
import api from '@/api/client'
import { setMemberCsrf } from '@/api/memberCsrf'

afterEach(() => { setMemberCsrf(null) })

it('sends the in-memory CSRF token only on same-origin writes', async () => {
  setMemberCsrf('test-token')
  const seen: (string | undefined)[] = []
  const adapter: AxiosAdapter = async config => {
    seen.push(config.headers.get('X-CSRF-Token') as string | undefined)
    return { data: null, status: 204, statusText: 'No Content', headers: {}, config }
  }
  await api.post('/api/example', null, { baseURL: window.location.origin, adapter })
  await api.get('/api/example', { baseURL: window.location.origin, adapter })
  await api.post('https://elsewhere.example/api/example', null, { adapter })
  expect(seen).toEqual(['test-token', undefined, undefined])
})
