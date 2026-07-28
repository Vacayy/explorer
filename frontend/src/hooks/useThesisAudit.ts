import { useMutation, useQuery } from "@tanstack/react-query"
import { apiQuery, postJson, STALE } from "@/api/query"
import type { ThesisAudit, ThesisAuditListItem } from "@/types"

/** 감사 실행 — 연쇄 LLM(~수 분). 긴 timeout. read-only(그래프 무변경). */
export function useRunThesisAudit() {
  return useMutation({
    mutationFn: (text: string) =>
      postJson<ThesisAudit>("/api/spine/thesis/audit", { text }, { timeout: 300_000 }),
  })
}

/** 감사 히스토리 (append-only) */
export function useThesisAudits() {
  return useQuery(
    apiQuery<ThesisAuditListItem[]>({
      key: ["spine", "thesis", "audits"], url: "/api/spine/thesis/audits", staleTime: STALE.short,
    }),
  )
}

/** 저장된 감사 재조회 (LLM 0) */
export function useThesisAudit(id: number | null) {
  return useQuery(
    apiQuery<ThesisAudit>({
      key: ["spine", "thesis", id], url: `/api/spine/thesis/${id}`, staleTime: STALE.long,
      enabled: id != null,
    }),
  )
}
