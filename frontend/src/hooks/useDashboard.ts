import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import type { Entry as LayoutEntry } from "@/components/widgets/rows"
import type { RiskResponse } from "@/types"

/** 지수 — IndexStrip과 같은 캐시 키(위젯과 전체 보기가 한 번만 받는다) */
export interface IndexRow { key: string; label: string; region: string; is_open: boolean; price: number | null; change_pct: number | null; spark: number[]; as_of: string | null }
export function useIndices() {
  return useQuery({
    ...apiQuery<{ as_of: string | null; items: IndexRow[]; degraded: string[]; any_open: boolean }>({ key: ["spine", "indices"], url: "/api/spine/indices", staleTime: STALE.medium }),
    refetchInterval: (q) => (q.state.data?.any_open ? 10 * 60_000 : 30 * 60_000),
    refetchIntervalInBackground: false,
  })
}

/** Risk 위젯 묶음 — 정본 계열(D-236)에서 3개월 창만 한 번에 (전 이력 1.4MB 대신 수 KB) */
export const RISK_WIDGET_KEYS = ["curve", "vix", "fear_greed", "hy"] as const
export function useRiskWindow() {
  return useQuery(apiQuery<RiskResponse>({
    key: ["spine", "risk", "window", "3m", RISK_WIDGET_KEYS.join(",")],
    url: `/api/spine/risk?range=3m&keys=${RISK_WIDGET_KEYS.join(",")}`, staleTime: STALE.short,
  }))
}

/** 홈 메뉴(보드) — 메뉴 하나 = 위젯 배치 하나(docs/specs/home-widgets.md §5). 홈 L2 탭이 이 목록이다 */
export interface HomeBoard { id: number; label: string; sort: number; items: LayoutEntry[]; updated_at: string }
const BOARDS_KEY = ["dashboard", "boards"] as const
const body = (items: LayoutEntry[]) => items.map(({ i, widget, x, y, w, h, params }) => ({ i, widget, x, y, w, h, params: params ?? {} }))
export function useHomeBoards() {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: BOARDS_KEY, queryFn: async () => (await api.get<HomeBoard[]>("/api/dashboard/boards")).data, staleTime: Infinity })
  const refresh = () => qc.invalidateQueries({ queryKey: BOARDS_KEY })
  /** 서버가 돌려준 메뉴로 캐시만 바꾼다 — 배치 저장마다 목록을 다시 받지 않는다 */
  const put = (b: HomeBoard) => qc.setQueryData<HomeBoard[]>(BOARDS_KEY, prev => prev?.map(x => x.id === b.id ? b : x))
  const create = useMutation({ mutationFn: async ({ label, items }: { label: string; items: LayoutEntry[] }) =>
    (await api.post<HomeBoard>("/api/dashboard/boards", { label, items: body(items) })).data, onSuccess: refresh })
  const update = useMutation({ mutationFn: async ({ id, label, items }: { id: number; label?: string; items?: LayoutEntry[] }) =>
    (await api.patch<HomeBoard>(`/api/dashboard/boards/${id}`, { ...(label ? { label } : {}), ...(items ? { items: body(items) } : {}) })).data, onSuccess: put })
  const order = useMutation({ mutationFn: async (ids: number[]) => (await api.put<HomeBoard[]>("/api/dashboard/boards/order", { ids })).data,
    onSuccess: data => qc.setQueryData(BOARDS_KEY, data) })
  const remove = useMutation({ mutationFn: async (id: number) => (await api.delete(`/api/dashboard/boards/${id}`)).data, onSuccess: refresh })
  return { ...query, create, update, order, remove }
}
