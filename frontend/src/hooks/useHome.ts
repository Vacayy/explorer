import { useQuery } from "@tanstack/react-query";
import { fetchHome, spineKeys } from "@/api/spine";

export function useHome() {
  return useQuery({
    queryKey: spineKeys.home(),
    queryFn: fetchHome,
    staleTime: 60_000, // 홈은 1분 (cron 주기 30분이므로 충분)
  });
}
