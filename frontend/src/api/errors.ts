import axios from 'axios'

export type ApiErrorKind = 'http' | 'network' | 'timeout' | 'schema' | 'unknown'

export class ApiError extends Error {
  readonly status?: number
  readonly kind: ApiErrorKind
  readonly issues?: readonly { path: PropertyKey[]; message: string }[]
  constructor(message: string, status?: number, options: {
    kind?: ApiErrorKind; cause?: unknown; issues?: readonly { path: PropertyKey[]; message: string }[]
  } = {}) {
    super(message, { cause: options.cause })
    this.name = 'ApiError'
    this.status = status
    this.kind = options.kind ?? (status ? 'http' : 'unknown')
    this.issues = options.issues
  }
}

export function isCancelled(error: unknown) {
  return axios.isCancel(error) || (error instanceof Error && error.name === 'AbortError')
}

/** Cancellation is control flow; callers must not convert it into a user-facing failure. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (axios.isAxiosError(error)) {
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return new ApiError('응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.', undefined, { kind: 'timeout', cause: error })
    }
    if (!error.response) return new ApiError('서버에 연결할 수 없습니다. 네트워크 연결을 확인해 주세요.', undefined, { kind: 'network', cause: error })
  }
  // Also accept error-like values from legacy request wrappers.
  const err = error as { response?: { status?: number; data?: { detail?: unknown } } } | null
  const status = err?.response?.status
  const detail = err?.response?.data?.detail
  const validation = Array.isArray(detail) ? detail.flatMap(d => typeof d?.msg === 'string' ? [d.msg] : []).join(' · ') : undefined
  const message = status && status >= 500 ? '서버에서 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'
    : typeof detail === 'string' && detail.trim() ? detail
    : validation || (status === 401 ? '로그인이 필요합니다.' : status === 403 ? '접근 권한이 없습니다.'
      : status === 404 ? '요청한 정보를 찾을 수 없습니다.' : status === 429 ? '요청이 많습니다. 잠시 후 다시 시도해 주세요.'
      : '요청을 처리하지 못했습니다. 다시 시도해 주세요.')
  return new ApiError(message, status, { cause: error })
}

export function shouldRetry(failureCount: number, error: unknown) {
  if (isCancelled(error)) return false
  const normalized = toApiError(error)
  return failureCount < 1 && (normalized.kind === 'network' || normalized.kind === 'timeout'
    || (normalized.kind === 'http' && (normalized.status === 408 || normalized.status === 429 || (normalized.status ?? 0) >= 500)))
}
