// @vitest-environment node
import { afterAll, beforeAll, expect, it } from 'vitest'
import { createServer, type Server } from 'node:http'
import { CanceledError } from 'axios'
import api from '../src/api/client'

let server: Server
let root: string
beforeAll(async () => {
  server = createServer((req, res) => {
    if (req.url === '/slow') return // Intentionally never responds; client must stop waiting.
    res.setHeader('Content-Type', 'application/json')
    if (req.url === '/error') { res.statusCode = 503; res.end('{"detail":"internal diagnostic"}'); return }
    res.end(req.url === '/invalid' ? '{broken' : '{"ok":true}')
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  root = `http://127.0.0.1:${(server.address() as { port: number }).port}`
})
afterAll(async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())) })
it('enforces actual timeouts and abort signals', async () => {
  await expect(api.get(`${root}/slow`, { timeout: 30 })).rejects.toMatchObject({ kind: 'timeout' })
  const controller = new AbortController()
  const request = api.get(`${root}/slow`, { signal: controller.signal })
  controller.abort()
  await expect(request).rejects.toBeInstanceOf(CanceledError)
})
it('rejects real HTTP failures and malformed JSON', async () => {
  await expect(api.get(`${root}/error`)).rejects.toMatchObject({ kind: 'http', status: 503 })
  await expect(api.get(`${root}/invalid`)).rejects.toMatchObject({ kind: 'schema' })
  await expect(api.get(`${root}/ok`)).resolves.toMatchObject({ data: { ok: true } })
})
