import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import type { StockGroupDetail, StockGroupKind, StockGroupList, StrategyCatalogItem, WatchRuleInput, GroupDigest, GroupSignal, WatchReason } from '@/types'

const ROOT = '/api/spine/groups'
export const groupKeys = {
  list: ['spine', 'groups'] as const,
  detail: (id: number | null) => ['spine', 'group', id] as const,
  signals: (id: number | null, days: number) => ['spine', 'group-signals', id, days] as const,
  defaultWatch: ['spine', 'group', 'default-watch'] as const,
}
const defaultWatchQuery = { queryKey: groupKeys.defaultWatch, queryFn: async () => (await api.get<StockGroupDetail>(`${ROOT}/default-watch`)).data }

export function useGroups() {
  return useQuery({ queryKey: groupKeys.list, queryFn: async () => (await api.get<StockGroupList>(ROOT)).data })
}
export function useGroup(id: number | null) {
  return useQuery({ queryKey: groupKeys.detail(id), queryFn: async () => (await api.get<StockGroupDetail>(`${ROOT}/${id}`)).data, enabled: id != null })
}
export function useGroupSignals(id: number | null, days = 30) {
  return useQuery({ queryKey: groupKeys.signals(id, days), queryFn: async () => (await api.get<{ items: GroupSignal[] }>(`${ROOT}/${id}/signals`, { params: { days } })).data.items, enabled: id != null })
}
/** 묶음 종목별 최신 1D 요약 — 읽기만(생성은 저녁 잡) */
export function useGroupDigests(id: number | null) {
  return useQuery({ queryKey: ['spine', 'group-digests', id], queryFn: async () => (await api.get<{ as_of: string | null; items: GroupDigest[] }>(`${ROOT}/${id}/digests`)).data, enabled: id != null, staleTime: 300_000 })
}
/** 기본 관심 묶음('관심 종목') — 기업 화면 ★·내 목록 종목·논지가 쓰는 관심 종목의 진실원천. 서버가 없으면 만든다. */
export function useDefaultWatchGroup() {
  return useQuery(defaultWatchQuery)
}
export function useStrategyCatalog() {
  return useQuery({ queryKey: ['market-analysis', 'strategies'], queryFn: async () => (await api.get<{ version: string; items: StrategyCatalogItem[] }>('/api/analysis/strategies')).data.items, staleTime: Infinity })
}

/** 상세 응답을 캐시에 반영하고 목록·신호를 새로 읽는다. */
function useGroupWrite<TVariables>(mutationFn: (variables: TVariables) => Promise<StockGroupDetail>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: detail => {
      client.setQueryData(groupKeys.detail(detail.id), detail)
      client.invalidateQueries({ queryKey: groupKeys.list })
      client.invalidateQueries({ queryKey: ['spine', 'group-signals', detail.id] })
      client.invalidateQueries({ queryKey: groupKeys.defaultWatch })
    },
  })
}

export function useCreateGroup() { return useGroupWrite(async (body: { name: string; kind: StockGroupKind; note?: string }) => (await api.post<StockGroupDetail>(ROOT, body)).data) }
export function useUpdateGroup(id: number) { return useGroupWrite(async (body: { name?: string; kind?: StockGroupKind; note?: string }) => (await api.patch<StockGroupDetail>(`${ROOT}/${id}`, body)).data) }
export function useDeleteGroup() {
  const client = useQueryClient()
  return useMutation({ mutationFn: async (id: number) => { await api.delete(`${ROOT}/${id}`) }, onSuccess: () => client.invalidateQueries({ queryKey: groupKeys.list }) })
}
export function useAddMember() {
  return useGroupWrite(async ({ groupId, ...body }: { groupId: number; stock_code: string; conviction?: number; target_price?: number; thesis?: string }) =>
    (await api.post<StockGroupDetail>(`${ROOT}/${groupId}/members`, body)).data)
}
export function useUpdateMember(groupId: number) {
  return useGroupWrite(async ({ stockCode, ...body }: { stockCode: string; conviction?: number | null; target_price?: number | null; thesis?: string | null }) =>
    (await api.patch<StockGroupDetail>(`${ROOT}/${groupId}/members/${stockCode}`, body)).data)
}
export function useRemoveMember(groupId: number) { return useGroupWrite(async (stockCode: string) => (await api.delete<StockGroupDetail>(`${ROOT}/${groupId}/members/${stockCode}`)).data) }
export function usePutRules(groupId: number) {
  return useGroupWrite(async (body: { default: WatchRuleInput[]; members: Record<string, WatchRuleInput[]> }) => (await api.put<StockGroupDetail>(`${ROOT}/${groupId}/rules`, body)).data)
}
export function useEvaluateGroup(groupId: number) {
  return useGroupWrite(async (force = false) => (await api.post<{ summary: unknown; group: StockGroupDetail }>(`${ROOT}/${groupId}/evaluate`, null, { params: { force } })).data.group)
}
/** ★ — 기본 관심 묶음에 넣거나 뺀다. */
export function useToggleWatch() {
  const client = useQueryClient()
  return useGroupWrite(async ({ stockCode, watched }: { stockCode: string; watched: boolean }) => {
    const group = await client.ensureQueryData(defaultWatchQuery)
    return watched
      ? (await api.post<StockGroupDetail>(`${ROOT}/${group.id}/members`, { stock_code: stockCode })).data
      : (await api.delete<StockGroupDetail>(`${ROOT}/${group.id}/members/${stockCode}`)).data
  })
}
/** 종목 논지 저장 — 기본 관심 묶음 멤버의 thesis. 묶음에 없으면 먼저 넣는다(종목 브리프의 논지 점검 기준). */
export function useSetWatchThesis() {
  const client = useQueryClient()
  return useGroupWrite(async ({ stockCode, thesis }: { stockCode: string; thesis: string }) => {
    const group = await client.ensureQueryData(defaultWatchQuery)
    await api.post(`${ROOT}/${group.id}/members`, { stock_code: stockCode })
    return (await api.patch<StockGroupDetail>(`${ROOT}/${group.id}/members/${stockCode}`, { thesis })).data
  })
}

/** 발견 화면의 저장 전략 조건을 묶음 기본 규칙에 덧붙인다(같은 전략·매개변수는 한 번만). */
export function useAppendDefaultRules() {
  return useGroupWrite(async ({ groupId, rules }: { groupId: number; rules: WatchRuleInput[] }) => {
    const detail = (await api.get<StockGroupDetail>(`${ROOT}/${groupId}`)).data
    const toInput = (rule: { strategy_id: string; params: Record<string, unknown>; within_days: number; source_strategy_id?: string | null; source_version?: number | null }): WatchRuleInput =>
      ({ strategy_id: rule.strategy_id, params: rule.params, within_days: rule.within_days, source_strategy_id: rule.source_strategy_id ?? null, source_version: rule.source_version ?? null })
    const key = (rule: WatchRuleInput) => `${rule.strategy_id}:${JSON.stringify(rule.params ?? {})}:${rule.within_days ?? 1}`
    const current = detail.rules.default.map(toInput)
    const seen = new Set(current.map(key))
    const merged = [...current, ...rules.filter(rule => !seen.has(key(rule)))]
    const members = Object.fromEntries(Object.entries(detail.rules.members).map(([code, list]) => [code, list.map(toInput)]))
    return (await api.put<StockGroupDetail>(`${ROOT}/${groupId}/rules`, { default: merged, members })).data
  })
}

/** 그린 차트 구조를 종목별 감시 규칙으로 덧붙인다(D-196). 종목이 묶음에 없으면 먼저 넣는다. 같은 전략·매개변수는 한 번만. */
export function useAppendMemberRule() {
  return useGroupWrite(async ({ groupId, stockCode, rule }: { groupId: number; stockCode: string; rule: WatchRuleInput }) => {
    let detail = (await api.get<StockGroupDetail>(`${ROOT}/${groupId}`)).data
    if (!detail.members.some(member => member.stock_code === stockCode)) detail = (await api.post<StockGroupDetail>(`${ROOT}/${groupId}/members`, { stock_code: stockCode })).data
    const toInput = (item: { strategy_id: string; params: Record<string, unknown>; within_days: number; source_strategy_id?: string | null; source_version?: number | null }): WatchRuleInput =>
      ({ strategy_id: item.strategy_id, params: item.params, within_days: item.within_days, source_strategy_id: item.source_strategy_id ?? null, source_version: item.source_version ?? null })
    const key = (item: WatchRuleInput) => `${item.strategy_id}:${JSON.stringify(item.params ?? {})}:${item.within_days ?? 1}`
    const members = Object.fromEntries(Object.entries(detail.rules.members).map(([code, list]) => [code, list.map(toInput)]))
    const current = members[stockCode] ?? []
    if (!current.some(item => key(item) === key(rule))) members[stockCode] = [...current, rule]
    return (await api.put<StockGroupDetail>(`${ROOT}/${groupId}/rules`, { default: detail.rules.default.map(toInput), members })).data
  })
}

/** 관심 종목 이유(D-227) — 판정은 매일 07:40, 알림은 텔레그램만. */
export function useGroupReasons(id: number) {
  return useQuery({ queryKey: ['spine', 'group-reasons', id], queryFn: async () => (await api.get<Record<string, WatchReason>>(`${ROOT}/${id}/reasons`)).data })
}
/** 이유 감시 시작 — 서버가 sonnet 1회로 분해(1~3분). */
export function useStartReason(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: { stock_code: string; why: string; trigger: string }) => (await api.post<{ id: number }>(`${ROOT}/${id}/reasons`, body, { timeout: 300_000 })).data,
    onSuccess: () => client.invalidateQueries({ queryKey: ['spine', 'group-reasons', id] }),
  })
}
