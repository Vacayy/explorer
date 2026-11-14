import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { chatTargetsQuery } from "@/api/spine"
import type { ChatTarget, ChatTargetKind } from "@/types"

/** 대상 후보 검색 (GET /api/spine/chat/targets) — 입력이 멈춘 뒤 150ms에 부른다. items는 화면 순서대로 편 목록(↑↓ 이동용) */
export function useChatTargets(query: string, kind: ChatTargetKind | null, enabled: boolean) {
  const [debounced, setDebounced] = useState(query.trim())
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 150)
    return () => clearTimeout(t)
  }, [query])
  const q = useQuery(chatTargetsQuery(debounced, kind, enabled))
  const groups = useMemo(() => q.data?.groups ?? [], [q.data])
  const items = useMemo<ChatTarget[]>(() => groups.flatMap(g => g.items), [groups])
  return { ...q, groups, items, settledQuery: debounced }
}

/** cmdk 값 — 종류와 식별자 */
export const targetValue = (t: { kind: string; ref: string }) => `${t.kind}:${t.ref}`
