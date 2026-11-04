import axios from 'axios'
import { ApiError, isCancelled, toApiError } from './errors.ts'
import { validateResponse } from './contracts.ts'
import { reportApiError } from './telemetry.ts'

/** 백엔드 주소 — 워크트리처럼 다른 포트로 띄울 때 VITE_API_BASE로 바꾼다. */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'
export const REQUEST_TIMEOUT = 30_000

const api = axios.create({
  baseURL: API_BASE,
  timeout: REQUEST_TIMEOUT,
  headers: { Accept: 'application/json' },
})

/** 'GET /api/...' — 쿼리 문자열 없이. 오류 원인 표시·기록의 키 */
function endpointOf(config?: { method?: string; url?: string; baseURL?: string; params?: unknown }) {
  if (!config) return undefined
  const path = new URL(api.getUri(config as never), 'http://api.local').pathname
  return `${(config.method ?? 'get').toUpperCase()} ${path}`
}

/** 원인(API·필드)을 붙여 콘솔·서버에 남긴다 — 화면엔 일반 문구, 원인은 '자세히'와 운영 점검에서 (telemetry.ts) */
function traced(error: ApiError, config?: Parameters<typeof endpointOf>[0]) {
  error.endpoint ??= endpointOf(config)
  reportApiError(error, API_BASE)
  return error
}

api.interceptors.response.use(async response => {
  // JSON APIs returning an HTML proxy/login page must not enter the query cache.
  const contentType = String(response.headers['content-type'] ?? '')
  if (!response.config.responseType || response.config.responseType === 'json') {
    if (response.status !== 204 && (/text\/html/i.test(contentType) || typeof response.data === 'string')) {
      throw traced(new ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', response.status, { kind: 'schema' }), response.config)
    }
    try {
      response.data = await validateResponse(response.config.method ?? 'get', api.getUri(response.config), response.data, response.status)
    } catch (error) {
      throw error instanceof ApiError ? traced(error, response.config) : error
    }
  }
  return response
}, error => Promise.reject(isCancelled(error) ? error : traced(toApiError(error), error?.config)))

export default api
