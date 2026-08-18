import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, getJson, STALE } from "@/api/query"
import type { UsBriefing, UsBriefingListItem } from "@/types"

const KEY = ["spine", "us", "briefing"] as const

/**
 * 어젯밤 미국장 브리핑 — launchd `dev.explorer.usbriefing`(매일 07:30 KST)이 pre-warm한다.
 * refresh=수동 force 갱신(TradingView+뉴스+재종합). tradeDate=과거 브리핑 읽기 전용 조회(D-112).
 */
export function useUsBriefing(tradeDate?: string | null) {
  const qc = useQueryClient()
  const url = tradeDate ? `/api/spine/us/briefing?trade_date=${tradeDate}` : "/api/spine/us/briefing"
  const query = useQuery(apiQuery<UsBriefing>({ key: [...KEY, tradeDate ?? "latest"], url, staleTime: STALE.long }))
  const refresh = useMutation({
    mutationFn: () => getJson<UsBriefing>("/api/spine/us/briefing", { force: true }),
    onSuccess: (data) => qc.setQueryData([...KEY, "latest"], data),
  })
  return { ...query, refresh: () => refresh.mutate(), refreshing: refresh.isPending }
}

/** 저장된 브리핑 날짜 목록 — 과거 조회 셀렉터용 (D-112). */
export function useUsBriefingDates() {
  return useQuery(apiQuery<UsBriefingListItem[]>({
    key: ["spine", "us", "briefing", "list"],
    url: "/api/spine/us/briefing/list", staleTime: STALE.long,
  }))
}
