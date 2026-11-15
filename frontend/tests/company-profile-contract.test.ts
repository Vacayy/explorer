import { describe, it, expect } from 'vitest'
import routes from '@/api/generated/routes.json'
import * as validators from '@/api/generated/validators-company-profile.js'
import { execFileSync } from 'node:child_process'
const route = routes.find(r => r.method === 'get' && r.path === '/api/spine/company-profile/{code}')!
const validate = validators[route.validator as keyof typeof validators]
const response = (overview: string) => ({ profile: { id: 1, stock_code: 'NVDA', version: 1, created_at: '2026-11-01T00:00:00Z', source_count: 0, overview }, reuse_hours: 24, market: 'us' })
describe('generated company profile runtime helpers', () => {
  it('loads the generated CommonJS helper in native ESM', () => {
    const code = `import * as validators from './src/api/generated/validators-company-profile.js'; const validate=validators[${JSON.stringify(route.validator)}]; if(!validate(${JSON.stringify(response('기업 😀'))}))throw Error('Valid profile rejected');`
    expect(() => execFileSync(process.execPath, ['--input-type=module', '-e', code], { stdio: 'pipe' })).not.toThrow()
  })
  it('validates Unicode text using the actual generated length helper', () => {
    expect(validate(response('기업 개요 😀'))).toBe(true)
    expect(validate(response('😀'.repeat(2500)))).toBe(true)
  })
  it('keeps the backend text length limit enforced', () => {
    expect(validate(response('😀'.repeat(2501)))).toBe(false)
    expect(validate(response(''))).toBe(false)
  })
})
