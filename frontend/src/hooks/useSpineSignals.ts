import { useQuery } from "@tanstack/react-query";
import { fetchSpineSignals, spineKeys } from "@/api/spine";

export function useSpineSignals(type?: string, days?: number) {
  return useQuery({
    queryKey: spineKeys.signals(type, days),
    queryFn: () => fetchSpineSignals(type, days),
    staleTime: 5 * 60_000,
  });
}
