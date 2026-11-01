import { frontendContracts } from './frontend-contracts.mjs'
// Deterministic, offline generation from checked-out FastAPI response models.
// No server start, database initialization, collectors or external API calls.
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync, existsSync, unlinkSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import Ajv from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import standaloneCode from 'ajv/dist/standalone/index.js'

const root = fileURLToPath(new URL('../../', import.meta.url))
const python = process.env.EXPLORER_PYTHON ?? `${root}.venv/bin/python`
const spec = JSON.parse(execFileSync(python, ['-c', 'import json; from main import app; print(json.dumps(app.openapi()))'], {
  cwd: `${root}backend`, encoding: 'utf8', maxBuffer: 20 * 1024 * 1024,
}))
// Remove descriptions/examples/defaults to reduce bundle size; never add/coerce fields.
function compact(value) {
  if (Array.isArray(value)) return value.map(compact)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).filter(([key]) => !['title', 'description', 'examples', 'example', 'default'].includes(key)).map(([key, val]) => [key, ['properties', '$defs', 'definitions', 'dependentSchemas'].includes(key) ? Object.fromEntries(Object.entries(val).map(([name, schema]) => [name, compact(schema)])) : key === 'const' || key === 'enum' ? val : compact(val)]))
}
function draft2020(schema) {
  if (Array.isArray(schema)) return schema.map(draft2020)
  if (!schema || typeof schema !== 'object') return schema
  const result = Object.fromEntries(Object.entries(schema).map(([key, value]) => [key, draft2020(value)]))
  if (Array.isArray(result.items)) {
    result.prefixItems = result.items
    result.items = result.additionalItems ?? true
    delete result.additionalItems
  }
  return result
}
const ajv = new Ajv({ strict: false, allErrors: false, inlineRefs: false, code: { source: true, esm: true }, validateFormats: true })
addFormats(ajv)
ajv.addSchema({ $id: 'explorer', components: { schemas: compact(spec.components.schemas) } })
const routes = []
const exports = {}
const uncovered = []
for (const [path, methods] of Object.entries(spec.paths).sort(([a], [b]) => a.localeCompare(b))) {
  for (const [method, operation] of Object.entries(methods).sort(([a], [b]) => a.localeCompare(b))) {
    if (!['get', 'post', 'put', 'patch', 'delete'].includes(method)) continue
    const responses = Object.entries(operation.responses ?? {}).filter(([status]) => /^2\d\d$/.test(status))
    for (const [status, response] of responses) {
      const schema = response.content?.['application/json']?.schema
      if (!schema || !Object.keys(schema).length) { uncovered.push({ method, path, status: Number(status) }); continue }
      const name = `response${routes.length}`
      const resolved = JSON.parse(JSON.stringify(compact(schema)).replaceAll('"#/components/schemas/', '"explorer#/components/schemas/'))
      ajv.addSchema(resolved, name)
      exports[name] = name
      routes.push({ method, path, status: Number(status), validator: name })
    }
  }
}
// Supplement unmodeled operations with their explicitly declared frontend response types.
const supplemental = frontendContracts(root, uncovered)
const frontendGroups = new Map()
for (const contract of supplemental.contracts) {
  const key = `${contract.method} ${contract.path} ${contract.status}`
  if (!frontendGroups.has(key)) frontendGroups.set(key, [])
  frontendGroups.get(key).push(contract)
}
for (const contracts of frontendGroups.values()) {
  // Each caller may declare a different subset of the same response. All those subsets
  // must hold; accepting just one would allow invalid fields through to other screens.
  const refs = contracts.map((contract, index) => {
    const key = `frontend${routes.length}_${index}`
    const schema = draft2020(compact(contract.schema))
    delete schema.$schema
    ajv.addSchema(schema, key)
    return { $ref: key }
  })
  const name = `response${routes.length}`
  ajv.addSchema({ allOf: refs }, name)
  exports[name] = name
  const { method, path, status } = contracts[0]
  routes.push({ method, path, status, validator: name, source: 'frontend' })
}
const missing = uncovered.filter(operation => !frontendGroups.has(`${operation.method} ${operation.path} ${operation.status}`))
// Load only the validators needed by the requested domain; do not put every
// generated validator into the initial application bundle.
const groups = new Map()
for (const route of routes) {
  const parts = route.path.split('/').filter(Boolean)
  route.group = (parts[1] === 'spine' ? parts[2] : parts[1]).replace(/[^a-z0-9-]/gi, '-')
  if (!groups.has(route.group)) groups.set(route.group, {})
  groups.get(route.group)[route.validator] = exports[route.validator]
}
const files = {
  'routes.json': JSON.stringify(routes, null, 2) + '\n',
  'unmodeled.json': JSON.stringify(missing, null, 2) + '\n',
  'unresolved-types.json': JSON.stringify(supplemental.unresolved, null, 2) + '\n',
  'loaders.ts': '// Generated by npm run contracts:generate. Do not edit.\nexport const loaders = {\n' +
    [...groups.keys()].map(group => `  '${group}': () => import('./validators-${group}.js'),`).join('\n') + '\n}\n',
}
for (const [group, exports] of groups) {
  let code = standaloneCode(ajv, exports)
  // Convert Ajv CommonJS runtime expressions into static browser-bundle imports.
  const imports = new Map()
  code = code.replace(/require\("([^"\n]+)"\)/g, (_match, source) => {
    if (!source.startsWith('ajv/') && source !== 'ajv-formats/dist/formats') throw new Error(`Unexpected generated dependency: ${source}`)
    if (!imports.has(source)) imports.set(source, `helper${imports.size}`)
    return imports.get(source)
  })
  files[`validators-${group}.js`] = '// Generated by npm run contracts:generate. Do not edit.\n' +
    [...imports].map(([source, name]) => `import * as ${name} from '${source}.js';`).join('\n') + '\n' + code
  files[`validators-${group}.d.ts`] = `import type { ValidateFunction } from 'ajv'\n${Object.keys(exports).map(name => `export const ${name}: ValidateFunction`).join('\n')}\n`
}
if (!process.argv.includes('--check')) for (const legacy of ['validators.js', 'validators.d.ts']) {
  const path = `${root}frontend/src/api/generated/${legacy}`
  if (existsSync(path)) unlinkSync(path)
}
for (const [file, content] of Object.entries(files)) {
  const target = `${root}frontend/src/api/generated/${file}`
  if (process.argv.includes('--check')) {
    if (readFileSync(target, 'utf8') !== content) throw new Error(`Stale contracts: ${file}. Run npm run contracts:generate.`)
  } else writeFileSync(target, content)
}
console.log(`${routes.length} response contracts generated; ${missing.length} operations have no response contract (${supplemental.unresolved.length} unresolved frontend types).`)
