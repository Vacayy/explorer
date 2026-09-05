// 저장됨(북마크) 훅 — 목록 쿼리 + 저장/해제/메모 뮤테이션 (D-078)
// SavedItem 타입은 여기 co-locate (기능 로컬 타입).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { spineKeys } from "@/api/spine"

export type SavedKind = "company" | "doc" | "narrative" | "report" | "synthesis"

export interface SavedItem {
  id: number
  kind: SavedKind
  ref: string
  url: string
  title: string | null
  subtitle: string | null
  note: string | null
  created_at: string | null
}

export interface SaveInput {
  kind: SavedKind
  ref: string
  url: string
  title?: string | null
  subtitle?: string | null
  note?: string | null
}

/** 저장 목록 (배지·토글 상태·리스트 공용 — ApprovalsInbox 패턴) */
export function useSaved() {
  return useQuery(
    apiQuery<SavedItem[]>({ key: spineKeys.saved(), url: "/api/spine/saved", staleTime: STALE.short }),
  )
}

export function useAddSaved() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: SaveInput) => (await api.post("/api/spine/saved", body)).data as SavedItem,
    onSuccess: () => qc.invalidateQueries({ queryKey: spineKeys.saved() }),
  })
}

export function useRemoveSaved() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => { await api.delete(`/api/spine/saved/${id}`) },
    onSuccess: () => qc.invalidateQueries({ queryKey: spineKeys.saved() }),
  })
}

export function useUpdateSavedNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string | null }) =>
      (await api.patch(`/api/spine/saved/${id}`, { note })).data as SavedItem,
    onSuccess: () => qc.invalidateQueries({ queryKey: spineKeys.saved() }),
  })
}
