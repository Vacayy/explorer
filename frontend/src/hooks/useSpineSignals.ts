import { useQuery } from "@tanstack/react-query";
import { fetchSignalsSummary, fetchSpineSignals, spineKeys } from "@/api/spine";

export function useSpineSignals(type?: string, days?: number) {
  return useQuery({
    queryKey: spineKeys.signals(type, days),
    queryFn: () => fetchSpineSignals(type, days),
    staleTime: 5 * 60_000,
  });
}

/** 유형별 최신일 건수·상위 3 — 신호 인덱스·'오늘의 신호' 위젯 (읽기 전용 GET) */
export function useSignalsSummary(days = 7) {
  return useQuery({
    queryKey: spineKeys.signalsSummary(days),
    queryFn: () => fetchSignalsSummary(days),
    staleTime: 5 * 60_000,
  });
}
