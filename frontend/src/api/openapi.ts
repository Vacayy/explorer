import type { ValidateFunction } from 'ajv'
import { loaders } from './generated/loaders.ts'
import routes from './generated/routes.json' with { type: 'json' }
import unmodeled from './generated/unmodeled.json' with { type: 'json' }
import { ApiError } from './errors.ts'

const load = loaders as Record<string, () => Promise<object>>
// Resolve static routes before parameter routes, including unmodeled routes. A missing
// contract for /items/search must never accidentally use /items/{id}'s contract.
const operations = [...routes, ...unmodeled].map(route => ({
  ...route,
  pattern: new RegExp('^' + route.path.split('/').filter(Boolean).map(segment =>
    segment.startsWith('{') ? '[^/]+' : segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
  ).join('/') + '$'),
  specificity: route.path.split('/').filter(segment => segment && !segment.startsWith('{')).length,
})).sort((a, b) => b.specificity - a.specificity || b.path.split('/').length - a.path.split('/').length)

export function findResponseContract(method: string, path: string, status = 200) {
  const normalized = path.replace(/^\/+|\/+$/g, '')
  const route = operations.find(route => route.method === method.toLowerCase() && route.pattern.test(normalized))
  if (!route) return undefined
  // Different successful statuses may have different bodies (for example 204).
  const response = operations.find(candidate => candidate.method === route.method && candidate.path === route.path && candidate.status === status) ?? route
  return 'validator' in response && typeof response.validator === 'string' && 'group' in response && typeof response.group === 'string'
    ? { name: response.validator, group: response.group } : undefined
}

export async function validateOpenApiResponse(method: string, path: string, data: unknown, status = 200) {
  const contract = findResponseContract(method, path, status)
  if (!contract) return data
  let module: object
  try { module = await load[contract.group]() } catch (cause) {
    throw new ApiError('응답 검증 기능을 불러오지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.', undefined, { kind: 'network', cause })
  }
  const validate = (module as Record<string, ValidateFunction>)[contract.name]
  if (!validate(data)) {
    throw new ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', status, {
      kind: 'schema',
      issues: validate.errors?.map(error => ({
        path: error.instancePath.split('/').slice(1).map(part => part.replace(/~1/g, '/').replace(/~0/g, '~')),
        message: error.message ?? '응답 계약을 확인해 주세요.',
      })),
    })
  }
  return data
}
