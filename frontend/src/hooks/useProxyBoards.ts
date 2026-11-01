import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import type { ProxyAdapter, ProxyBoardDetail, ProxyBoardSummary, ProxyCatalogEntry, ProxyDirection, ProxySuggestion } from "@/types"

/** 프록시 보드 (D-240) — 읽기는 순수(LLM 0), 지표 제안만 POST에서 LLM 1회 */
const ROOT = "/api/spine/proxy-boards"
const KEY = ["spine", "proxy-boards"] as const

export function useProxyBoards() {
  return useQuery(apiQuery<ProxyBoardSummary[]>({ key: [...KEY, "list"], url: ROOT, staleTime: STALE.short }))
}
export function useProxyBoard(id: number | null) {
  return useQuery({ ...apiQuery<ProxyBoardDetail>({ key: [...KEY, "detail", id], url: `${ROOT}/${id}`, staleTime: STALE.short }), enabled: id != null })
}
export function useProxyAdapters() {
  return useQuery(apiQuery<ProxyAdapter[]>({ key: [...KEY, "adapters"], url: `${ROOT}/adapters`, staleTime: STALE.long }))
}
export function useProxyCatalog(kind: string | null, q: string) {
  return useQuery({
    queryKey: [...KEY, "catalog", kind, q],
    queryFn: async () => (await api.get<ProxyCatalogEntry[]>(`${ROOT}/adapters/${kind}/catalog`, { params: { q: q || undefined, limit: 50 } })).data,
    enabled: !!kind, staleTime: STALE.medium,
  })
}

export interface NewItem { label: string; adapter: string; adapter_ref: string; unit?: string | null; warn_direction?: ProxyDirection | null; rationale?: string | null }

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: KEY })
}
export function useSuggestProxies() {
  return useMutation({ mutationFn: async (topic: string) => (await api.post<ProxySuggestion>(`${ROOT}/suggest`, { topic }, { timeout: 300_000 })).data })
}
/** 보드 만들고 고른 지표를 차례로 담는다 */
export function useCreateProxyBoard() {
  const done = useInvalidate()
  return useMutation({
    mutationFn: async ({ name, description, items }: { name: string; description?: string; items: NewItem[] }) => {
      const board = (await api.post<ProxyBoardSummary>(ROOT, { name, description: description || null })).data
      for (const it of items) await api.post(`${ROOT}/${board.id}/items`, it)
      return board
    },
    onSuccess: done,
  })
}
export function useAddProxyItem(boardId: number) {
  const done = useInvalidate()
  return useMutation({ mutationFn: async (it: NewItem) => (await api.post(`${ROOT}/${boardId}/items`, it)).data, onSuccess: done })
}
export function useRemoveProxyItem(boardId: number) {
  const done = useInvalidate()
  return useMutation({ mutationFn: async (proxyId: number) => { await api.delete(`${ROOT}/${boardId}/items/${proxyId}`) }, onSuccess: done })
}
export function useDeleteProxyBoard() {
  const done = useInvalidate()
  return useMutation({ mutationFn: async (id: number) => { await api.delete(`${ROOT}/${id}`) }, onSuccess: done })
}
