import type { SavedItem } from "@/hooks/useSaved"

/** 저장됨 유형 필터 — 탭 옆에 건수를 붙인다 (ia-redesign §4.26) */
export const SAVED_FILTERS = [
  { value: "all", label: "전체" },
  { value: "company", label: "기업" },
  { value: "doc", label: "문서" },
  { value: "narrative", label: "내러티브" },
  { value: "report", label: "리포트" },
] as const
export type SavedFilter = (typeof SAVED_FILTERS)[number]["value"]

export function savedCounts(items: Pick<SavedItem, "kind">[]): Record<SavedFilter, number> {
  const out: Record<SavedFilter, number> = { all: items.length, company: 0, doc: 0, narrative: 0, report: 0 }
  for (const it of items) if (it.kind in out) out[it.kind] += 1
  return out
}
