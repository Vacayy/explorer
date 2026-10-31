import axios from 'axios'
import { ApiError, isCancelled, toApiError } from './errors.ts'
import { validateResponse } from './contracts.ts'

export const API_BASE = 'http://localhost:8000'
export const REQUEST_TIMEOUT = 30_000

const api = axios.create({
  baseURL: API_BASE,
  timeout: REQUEST_TIMEOUT,
  headers: { Accept: 'application/json' },
})

api.interceptors.response.use(async response => {
  // JSON APIs returning an HTML proxy/login page must not enter the query cache.
  const contentType = String(response.headers['content-type'] ?? '')
  if (!response.config.responseType || response.config.responseType === 'json') {
    if (response.status !== 204 && (/text\/html/i.test(contentType) || typeof response.data === 'string')) {
      throw new ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', response.status, { kind: 'schema' })
    }
    response.data = await validateResponse(response.config.method ?? 'get', api.getUri(response.config), response.data, response.status)
  }
  return response
}, error => Promise.reject(isCancelled(error) ? error : toApiError(error)))

export default api
