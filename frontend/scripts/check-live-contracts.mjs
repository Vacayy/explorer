// 실행 중인 백엔드의 실제 응답을 생성된 응답 계약으로 검사한다 (docs/specs/frontend-api-reliability.md §실제 응답 검사).
//
// contracts:check는 코드끼리(서버 모델·프런트 타입·생성물)만 비교해, 실제 데이터에서만 나오는 null·새 enum 값·
// 빠진 필드는 못 잡는다(2026-10-31: market_cap 누락, guidance 'unknown', lane 'web', published_at null).
// 이 검사는 GET 계약 전부를 예시 값(live-contract-samples.json)으로 호출해 검증하고, 실패를 콘솔과
// /api/spine/client-errors(page='live-check')에 남긴다 → 운영 점검 '화면 API 오류'에 오른다.
//
//   npm run contracts:live                 # 기본 http://localhost:8000
//   API_BASE=http://localhost:8011 npm run contracts:live
//   npm run contracts:live -- --no-report  # 기록 없이 결과만
// 종료 코드: 실패가 있으면 1(커밋 전 검사용), 없으면 0. 예시 값이 없어 호출하지 못한 계약은 목록으로만 알린다.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const base = process.env.API_BASE ?? 'http://localhost:8000'
const report = !process.argv.includes('--no-report')
const routes = JSON.parse(readFileSync(root + 'src/api/generated/routes.json', 'utf8'))
const samples = JSON.parse(readFileSync(root + 'scripts/live-contract-samples.json', 'utf8'))

const fill = path => samples.paths[path] ?? path.replace(/\{(\w+)\}/g, (_, k) => samples.params[k] ?? `{${k}}`)
const result = { ok: [], fail: [], unchecked: [], node: [] }

for (const r of routes) {
  if (r.method !== 'get' || r.status !== 200 || samples.skip.includes(r.path)) continue
  const path = fill(r.path)
  if (path.includes('{')) { result.unchecked.push(`${r.path} (경로 예시 값 없음)`); continue }
  const query = samples.query[r.path]
  const url = `${base}${encodeURI(path)}${query ? '?' + encodeURI(query) : ''}`
  let resp
  try { resp = await fetch(url, { signal: AbortSignal.timeout(30_000) }) } catch (e) { result.unchecked.push(`${r.path} (${e.name === 'TimeoutError' ? '30초 초과' : '연결 실패'})`); continue }
  if (resp.status !== 200) { result.unchecked.push(`${r.path} (HTTP ${resp.status}${query ? '' : ' — 쿼리 예시 값 필요?'})`); continue }
  let data
  try { data = await resp.json() } catch { result.fail.push({ route: r.path, field: '', detail: 'JSON 아님' }); continue }
  let ok
  try { ok = (await import(`${root}src/api/generated/validators-${r.group}.js`))[r.validator](data) } catch { result.node.push(r.path); continue }
  if (ok) { result.ok.push(r.path); continue }
  const v = (await import(`${root}src/api/generated/validators-${r.group}.js`))[r.validator]
  const e = v.errors?.[0] ?? {}
  result.fail.push({ route: r.path, field: (e.instancePath ?? '').split('/').slice(1).join('.'), detail: `${e.message ?? ''} ${JSON.stringify(e.params ?? {})}`.trim() })
}

for (const f of result.fail) {
  console.log(`FAIL GET ${f.route}  ${f.field}  ${f.detail}`)
  if (report) await fetch(`${base}/api/spine/client-errors`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ endpoint: `GET ${f.route}`, kind: 'schema', status: 200, field: f.field, detail: f.detail.slice(0, 500), page: 'live-check' }),
  }).catch(() => {})
}
console.log(`\n실제 응답 계약 검사 — 통과 ${result.ok.length} · 실패 ${result.fail.length} · 호출 못 함 ${result.unchecked.length} · node 검증 불가 ${result.node.length}`)
if (result.unchecked.length) console.log('호출 못 한 계약(예시 값을 scripts/live-contract-samples.json에 추가):\n  ' + result.unchecked.join('\n  '))
if (result.node.length) console.log('node에서 실행되지 않는 검증기(브라우저는 정상, ajv CJS 헬퍼):\n  ' + result.node.join('\n  '))
process.exit(result.fail.length ? 1 : 0)
