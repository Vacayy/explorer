import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchSpineFeed, spineKeys, type SpineFeedParams } from "@/api/spine";

export function useSpineFeed(params: SpineFeedParams) {
  return useQuery({
    queryKey: spineKeys.feed(params),
    queryFn: () => fetchSpineFeed(params),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData, // 페이지 전환 시 깜빡임 방지
  });
}
