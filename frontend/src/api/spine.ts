// spine(그래프 척추) API 계층 — queryKey factory + fetcher (frontend-plan.md Phase C)
import api from "@/api/client";
import type { HomeResponse, SpineFeedResponse, SpineSignalsResponse } from "@/types";

export interface SpineFeedParams {
  q?: string;
  source?: string;
  stock?: string;
  industry?: string;
  topic?: string;
  page?: number;
  size?: number;
}

export const spineKeys = {
  all: ["spine"] as const,
  home: () => [...spineKeys.all, "home"] as const,
  feed: (params: SpineFeedParams) => [...spineKeys.all, "feed", params] as const,
  signals: (type?: string, days?: number) => [...spineKeys.all, "signals", type ?? "all", days ?? 7] as const,
};

export async function fetchHome(): Promise<HomeResponse> {
  const { data } = await api.get<HomeResponse>("/api/spine/home");
  return data;
}

export async function fetchSpineFeed(params: SpineFeedParams): Promise<SpineFeedResponse> {
  const { data } = await api.get<SpineFeedResponse>("/api/spine/feed", { params });
  return data;
}

export async function fetchSpineSignals(type?: string, days?: number): Promise<SpineSignalsResponse> {
  const { data } = await api.get<SpineSignalsResponse>("/api/spine/signals", {
    params: { type, days },
  });
  return data;
}
