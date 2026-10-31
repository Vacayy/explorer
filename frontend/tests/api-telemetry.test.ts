// @vitest-environment node
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'
import { createServer, type Server } from 'node:http'
import api from '../src/api/client'

// 응답 계약 위반·5xx가 원인(API·필드)과 함께 서버 기록 엔드포인트로 보고되는지, 같은 오류는 한 번만 보고되는지
let server: Server
let root: string
beforeAll(async () => {
  server = createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json')
    if (req.url?.startsWith('/boom')) { res.statusCode = 503; res.end('{"detail":"x"}'); return }
    if (req.url?.startsWith('/missing')) { res.statusCode = 404; res.end('{"detail":"없음"}'); return }
    // 등록된 응답 계약(GET /api/spine/transcript/recent)이 요구하는 필드가 빠진 응답
    res.end('[{"transcript_id":1}]')
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  root = `http://127.0.0.1:${(server.address() as { port: number }).port}`
})
afterAll(async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())) })
afterEach(() => { vi.restoreAllMocks() })
// 보고 자체를 검사하므로 테스트 환경 차단을 이 파일에서만 푼다(fetch는 가짜로 바꿔 실제 서버로는 안 간다)
beforeAll(() => { (globalThis as { __API_TELEMETRY_TEST__?: boolean }).__API_TELEMETRY_TEST__ = true })
afterAll(() => { delete (globalThis as { __API_TELEMETRY_TEST__?: boolean }).__API_TELEMETRY_TEST__ })

const reports = (spy: ReturnType<typeof vi.fn>) => spy.mock.calls
  .filter(([url]) => String(url).endsWith('/api/spine/client-errors'))
  .map(([, init]) => JSON.parse((init as RequestInit).body as string))

it('reports contract violations with endpoint and field, once per signature', async () => {
  const spy = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
  vi.stubGlobal('fetch', spy)
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  const call = () => api.get('/api/spine/transcript/recent', { baseURL: root })
  await expect(call()).rejects.toMatchObject({ kind: 'schema', endpoint: 'GET /api/spine/transcript/recent' })
  await expect(call()).rejects.toMatchObject({ kind: 'schema' })
  const sent = reports(spy)
  expect(sent).toHaveLength(1)
  expect(sent[0]).toMatchObject({ endpoint: 'GET /api/spine/transcript/recent', kind: 'schema' })
  expect(sent[0].field).not.toBe('')
  vi.unstubAllGlobals()
})

it('reports 5xx but not 4xx', async () => {
  const spy = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
  vi.stubGlobal('fetch', spy)
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  await expect(api.get(`${root}/boom`)).rejects.toMatchObject({ kind: 'http', status: 503, endpoint: 'GET /boom' })
  await expect(api.get(`${root}/missing`)).rejects.toMatchObject({ kind: 'http', status: 404 })
  expect(reports(spy).map(r => r.endpoint)).toEqual(['GET /boom'])
  vi.unstubAllGlobals()
})
