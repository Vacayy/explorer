/**
 * TanStack Query 공통 계층 — 서버 상태 관리 규약.
 *
 * 모든 서버 통신은 이 유틸을 덧씌워 진행한다:
 * 1. 쿼리는 queryOptions 팩토리(apiQuery)로 선언 — 키·fetcher·stale이 한 곳에.
 * 2. 계산형 POST(LLM 생성 등 멱등 연산)도 apiComputeQuery로 '키잉된 쿼리'로 다룬다.
 *    키 없는 useMutation은 응답 도착 시점의 최신 렌더 클로저에 결과를 쓰므로,
 *    파라미터만 바뀌는 화면(/source?key=)에서 A의 응답이 B에 오염된다 — 실제 발생 버그.
 *    응답은 항상 자기 queryKey 슬롯에만 적재돼야 한다.
 * 3. 에러는 ApiError로 정규화 (백엔드 detail 메시지 추출).
 * 4. useMutation은 '서버 데이터를 변경'하는 쓰기(등록/삭제/토글)에만 쓴다.
 */
import { MutationCache, QueryCache, QueryClient, keepPreviousData, queryOptions } from "@tanstack/react-query"
import api from "./client.ts"
import { isCancelled, shouldRetry, toApiError } from "./errors.ts"
import { parseResponse } from "./contracts.ts"
export { ApiError, toApiError } from "./errors.ts"

/** stale 표준값 — 화면별 임의 숫자 대신 데이터 성격으로 선택 */
export const STALE = {
  realtime: 0,               // 항상 재검증 (홈 브리핑 등)
  short: 60_000,             // 1분 — 목록·도시에
  medium: 5 * 60_000,        // 5분 — 구독 목록·헬스
  long: 30 * 60_000,         // 30분 — 마스터성 데이터
  永: Infinity,              // 계산 결과 — 키가 곧 입력이므로 불변
} as const

export async function getJson<T>(url: string, params?: Record<string, unknown>, config?: { signal?: AbortSignal; schema?: { parse: (data: unknown) => T } }): Promise<T> {
  try {
    const { data } = await api.get<T>(url, { params, signal: config?.signal })
    return config?.schema ? parseResponse(config.schema, data) : data
  } catch (e) {
    throw isCancelled(e) ? e : toApiError(e)
  }
}

export async function postJson<T>(url: string, body?: unknown, config?: {
  params?: Record<string, unknown>
  timeout?: number
  signal?: AbortSignal
  schema?: { parse: (data: unknown) => T }
}): Promise<T> {
  try {
    const { data } = await api.post<T>(url, body ?? null, config)
    return config?.schema ? parseResponse(config.schema, data) : data
  } catch (e) {
    throw isCancelled(e) ? e : toApiError(e)
  }
}

/** 읽기 쿼리 선언 — useQuery(apiQuery({...}))로 사용. useSuspenseQuery에도 그대로 전달 가능. */
export function apiQuery<T>(opts: {
  key: readonly unknown[]
  url: string
  params?: Record<string, unknown>
  staleTime?: number
  schema?: { parse: (data: unknown) => T }
  /** 페이지네이션 등 파라미터 전환 시 이전 데이터 유지 (깜빡임 방지) */
  keepPrevious?: boolean
  enabled?: boolean
}) {
  return queryOptions<T>({
    queryKey: [...opts.key],
    queryFn: ({ signal }) => getJson<T>(opts.url, opts.params, { signal, schema: opts.schema }),
    staleTime: opts.staleTime ?? STALE.short,
    placeholderData: opts.keepPrevious ? (keepPreviousData as never) : undefined,
    enabled: opts.enabled,
  })
}

/**
 * 계산형 쿼리 — 서버에서 멱등인 POST(같은 입력이면 캐시 즉답)를 키잉된 서버 상태로.
 * 결과는 자기 키 슬롯에만 적재되므로 화면 전환 중 응답 오염이 구조적으로 불가능.
 * 오래 걸리는 연산 전제: 기본 timeout 180s, 재시도 없음, 결과 불변(staleTime ∞).
 */
export function apiComputeQuery<T>(opts: {
  key: readonly unknown[]
  url: string
  params?: Record<string, unknown>
  enabled?: boolean
  timeout?: number
  schema?: { parse: (data: unknown) => T }
}) {
  return queryOptions<T>({
    queryKey: [...opts.key],
    queryFn: ({ signal }) => postJson<T>(opts.url, null, { params: opts.params, timeout: opts.timeout ?? 180_000, signal, schema: opts.schema }),
    staleTime: STALE.永,
    gcTime: STALE.long,
    retry: false,
    enabled: opts.enabled,
  })
}

/** A single notification per failed query (not per observer); local mutation handlers take precedence. */
export function createQueryClient(onError?: (error: Error, context: { background: boolean }) => void) {
  return new QueryClient({
    queryCache: new QueryCache({ onError: (error, query) => {
      if (!isCancelled(error)) onError?.(toApiError(error), { background: query.state.data !== undefined })
    } }),
    mutationCache: new MutationCache({ onError: (error, _variables, _context, mutation) => {
      if (!mutation.options.onError && !isCancelled(error)) onError?.(toApiError(error), { background: false })
    } }),
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
}
