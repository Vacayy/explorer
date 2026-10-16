import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import type { ActionKind, ActionsResponse, CorporateAction, MyGroup, RightsResponse } from "@/types"

/** 기업활동 — 30분 주기 DART 스캔의 저장분만 읽는다(LLM·네트워크 0) */
export function useActions({ type, days = 30, kind = "all", stockCode }: { type?: string; days?: number; kind?: ActionKind; stockCode?: string } = {}) {
  const qs = new URLSearchParams({ days: String(days), kind })
  if (type) qs.set("type", type)
  if (stockCode) qs.set("stock_code", stockCode)
  return useQuery(apiQuery<ActionsResponse>({ key: ["spine", "actions", type ?? "", days, kind, stockCode ?? ""], url: `/api/spine/actions?${qs}`, staleTime: STALE.medium }))
}
export function useRights() {
  return useQuery(apiQuery<RightsResponse>({ key: ["spine", "actions", "rights"], url: "/api/spine/actions/rights", staleTime: STALE.medium }))
}

const GROUP_RANK: Record<MyGroup, number> = { 보유: 0, 관심: 1 }
/** 내 종목(보유 → 관심)을 위로, 나머지는 원래 순서(접수일 역순) 유지 */
export function pinMine<T extends Pick<CorporateAction, "my_group">>(items: T[]): T[] {
  return items.map((a, i) => ({ a, i }))
    .sort((x, y) => (x.a.my_group ? GROUP_RANK[x.a.my_group] : 2) - (y.a.my_group ? GROUP_RANK[y.a.my_group] : 2) || x.i - y.i)
    .map(({ a }) => a)
}
