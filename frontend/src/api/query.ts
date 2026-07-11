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
import { QueryClient, keepPreviousData, queryOptions } from "@tanstack/react-query"
import api from "@/api/client"

/** stale 표준값 — 화면별 임의 숫자 대신 데이터 성격으로 선택 */
export const STALE = {
  realtime: 0,               // 항상 재검증 (홈 브리핑 등)
  short: 60_000,             // 1분 — 목록·도시에
  medium: 5 * 60_000,        // 5분 — 구독 목록·헬스
  long: 30 * 60_000,         // 30분 — 마스터성 데이터
  永: Infinity,              // 계산 결과 — 키가 곧 입력이므로 불변
} as const

export class ApiError extends Error {
  readonly status?: number
  constructor(message: string, status?: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

/** axios 예외 → ApiError (FastAPI {detail} 우선) */
export function toApiError(e: unknown): ApiError {
  const err = e as { response?: { status?: number; data?: { detail?: string } }; message?: string }
  return new ApiError(err?.response?.data?.detail ?? err?.message ?? "요청 실패", err?.response?.status)
}

export async function getJson<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  try {
    const { data } = await api.get<T>(url, { params })
    return data
  } catch (e) {
    throw toApiError(e)
  }
}

export async function postJson<T>(url: string, body?: unknown, config?: {
  params?: Record<string, unknown>
  timeout?: number
}): Promise<T> {
  try {
    const { data } = await api.post<T>(url, body ?? null, config)
    return data
  } catch (e) {
    throw toApiError(e)
  }
}

/** 읽기 쿼리 선언 — useQuery(apiQuery({...}))로 사용. useSuspenseQuery에도 그대로 전달 가능. */
export function apiQuery<T>(opts: {
  key: readonly unknown[]
  url: string
  params?: Record<string, unknown>
  staleTime?: number
  /** 페이지네이션 등 파라미터 전환 시 이전 데이터 유지 (깜빡임 방지) */
  keepPrevious?: boolean
  enabled?: boolean
}) {
  return queryOptions<T>({
    queryKey: [...opts.key],
    queryFn: () => getJson<T>(opts.url, opts.params),
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
}) {
  return queryOptions<T>({
    queryKey: [...opts.key],
    queryFn: () => postJson<T>(opts.url, null, { params: opts.params, timeout: opts.timeout ?? 180_000 }),
    staleTime: STALE.永,
    gcTime: STALE.long,
    retry: false,
    enabled: opts.enabled,
  })
}

/** 앱 전역 QueryClient — 4xx는 재시도 무의미, 나머지 1회 */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          const status = error instanceof ApiError ? error.status : undefined
          if (status && status >= 400 && status < 500) return false
          return failureCount < 1
        },
        refetchOnWindowFocus: false,
      },
    },
  })
}
