/** 관리자 › 소스 요약 4칸 — /api/spine/sources/health 값으로만 센다(새 API 없음, ia-redesign §4.26) */
export interface SourceHealthLike { kind: string; docs_7d: number; warning: boolean; collect_enabled: boolean }

export function sourcesSummary(items: SourceHealthLike[]) {
  const byKind: Record<string, number> = {}
  for (const i of items) byKind[i.kind] = (byKind[i.kind] ?? 0) + 1
  return {
    total: items.length,
    byKind,
    docs7d: items.reduce((s, i) => s + i.docs_7d, 0),
    quiet: items.filter(i => i.warning).length,
    collectOff: items.filter(i => !i.collect_enabled).length,
  }
}
