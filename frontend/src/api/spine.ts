// spine(그래프 척추) API 계층 — queryKey factory + fetcher (frontend-plan.md Phase C)
import api from "@/api/client";
import { STALE, apiComputeQuery, apiQuery } from "@/api/query";
import type { AskResponse, ConversationDetail, ConversationItem, DossierSummary, HomeResponse, LensBundle, LensReading, SourceDossier, SpineFeedResponse, SpineSignalsResponse, StockBrief, UsDossier, UsList, UsMention, UsWorldModel } from "@/types";

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
  sourceDossier: (kind: string, key: string) => [...spineKeys.all, "source-dossier", kind, key] as const,
  sourceSummary: (kind: string, key: string) => [...spineKeys.all, "source-summary", kind, key] as const,
  stockBrief: (code: string) => [...spineKeys.all, "stock-brief", code] as const,
  stockBriefCompute: (code: string) => [...spineKeys.all, "stock-brief-compute", code] as const,
  conversations: (stock?: string) => [...spineKeys.all, "conversations", stock ?? "all"] as const,
  conversation: (id: number) => [...spineKeys.all, "conversation", id] as const,
  saved: () => [...spineKeys.all, "saved"] as const,
  stockLens: (code: string, market: string) => [...spineKeys.all, "stock-lens", code, market] as const,
  stockLensCompute: (code: string, type: string, market: string) => [...spineKeys.all, "stock-lens-compute", code, type, market] as const,
  usDossier: (ticker: string) => [...spineKeys.all, "us-dossier", ticker] as const,
  usList: () => [...spineKeys.all, "us-list"] as const,
  usMentions: (ticker: string) => [...spineKeys.all, "us-mentions", ticker] as const,
  usWorldModel: (ticker: string) => [...spineKeys.all, "us-worldmodel", ticker] as const,
};

/** 종목 AI 브리프 — 캐시 + stale 플래그 (LLM 없음) */
export const stockBriefQuery = (code: string) =>
  apiQuery<StockBrief>({
    key: spineKeys.stockBrief(code),
    url: `/api/spine/stock/${code}/brief`,
    staleTime: STALE.short,
    enabled: !!code,
  });

export const stockBriefHistoryQuery = (code: string, enabled: boolean) =>
  apiQuery<{ brief: string | null; thesis_check: string | null; created_at: string }[]>({
    key: [...spineKeys.stockBrief(code), "history"],
    url: `/api/spine/stock/${code}/brief/history`,
    staleTime: STALE.medium,
    enabled,
  });

/** 브리프 생성 — 입력(다이제스트·신호·일정·논지) 변경 시만 LLM. 종목별 키잉. */
export const stockBriefComputeQuery = (code: string, enabled: boolean) =>
  apiComputeQuery<StockBrief>({
    key: spineKeys.stockBriefCompute(code),
    url: `/api/spine/stock/${code}/brief/compute`,
    enabled,
  });

/** 투자 렌즈 — 캐시 + stale 플래그 (LLM 없음). market=kr|us */
export const stockLensQuery = (code: string, market = "kr") =>
  apiQuery<LensBundle>({
    key: spineKeys.stockLens(code, market),
    url: `/api/spine/stock/${code}/lens?market=${market}`,
    staleTime: STALE.short,
    enabled: !!code,
  });

/** 렌즈 생성 — 원칙·재료 변경 시만 LLM. 종목·렌즈·시장별 키잉. */
export const stockLensComputeQuery = (code: string, type: string, market: string, enabled: boolean) =>
  apiComputeQuery<LensReading>({
    key: spineKeys.stockLensCompute(code, type, market),
    url: `/api/spine/stock/${code}/lens/compute?type=${type}&market=${market}`,
    enabled,
  });

/** 미국 종목 도시에 헤더 — yfinance 시세·밸류 + 컨콜 메타 */
export const usDossierQuery = (ticker: string) =>
  apiQuery<UsDossier>({
    key: spineKeys.usDossier(ticker),
    url: `/api/spine/us/${ticker}`,
    staleTime: STALE.medium,
    enabled: !!ticker,
  });

/** 미국 종목 디렉토리 — transcript_follow 그룹별 + 캐시된 렌즈 stance (LLM 없음) */
export const usListQuery = () =>
  apiQuery<UsList>({ key: spineKeys.usList(), url: `/api/spine/us`, staleTime: STALE.medium });

/** 미국 종목 언급(여론) — entity_links 경유 최근 문서 */
export const usMentionsQuery = (ticker: string) =>
  apiQuery<UsMention[]>({
    key: spineKeys.usMentions(ticker),
    url: `/api/spine/us/${ticker}/mentions`,
    staleTime: STALE.medium,
    enabled: !!ticker,
  });

/** 미국 종목 월드모델 위치 — 인과 엣지 + 걸린 내러티브 (LLM 없음) */
export const usWorldModelQuery = (ticker: string) =>
  apiQuery<UsWorldModel>({
    key: spineKeys.usWorldModel(ticker),
    url: `/api/spine/us/${ticker}/worldmodel`,
    staleTime: STALE.medium,
    enabled: !!ticker,
  });

export const conversationsQuery = (stock?: string) =>
  apiQuery<ConversationItem[]>({
    key: spineKeys.conversations(stock),
    url: "/api/spine/conversations",
    params: stock ? { stock } : undefined,
    staleTime: STALE.short,
  });

export const conversationDetailQuery = (id: number, enabled: boolean) =>
  apiQuery<ConversationDetail>({
    key: spineKeys.conversation(id),
    url: `/api/spine/conversations/${id}`,
    staleTime: STALE.medium,
    enabled,
  });

/** 소스 도시에 — LLM 없이 즉시 응답 (캐시된 프로필 + stale 플래그) */
export const sourceDossierQuery = (kind: string, key: string) =>
  apiQuery<SourceDossier>({
    key: spineKeys.sourceDossier(kind, key),
    url: "/api/spine/sources/dossier",
    params: { kind, key },
    staleTime: STALE.short,
    enabled: !!kind && !!key,
  });

/**
 * 관점 프로필 생성 — 서버 멱등(새 글 있을 때만 LLM, 아니면 캐시 즉답).
 * (kind, key)로 키잉된 계산 쿼리: 응답이 항상 자기 소스 슬롯에만 적재된다.
 */
export const sourceSummaryQuery = (kind: string, key: string, enabled: boolean) =>
  apiComputeQuery<DossierSummary>({
    key: spineKeys.sourceSummary(kind, key),
    url: "/api/spine/sources/dossier/summary",
    params: { kind, key },
    enabled,
  });

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

export async function askQuestion(params: {
  question: string;
  document_ids?: number[];
  conversation_id?: number;
  /** 드래그 인용 — 선택 문장 + 문단 맥락 + 그 대목의 근거 (D-146) */
  quote?: { message_id: number; selected: string; block: string; citations: { n: number; kind?: string; title: string; doc_id: number | null }[] };
}): Promise<AskResponse> {
  const { data } = await api.post<AskResponse>("/api/spine/ask", params, { timeout: 300_000 });
  return data;
}

/** 스레드 제목 편집 (D-145) */
export async function renameConversation(params: { id: number; title: string }): Promise<ConversationItem> {
  const { data } = await api.patch<ConversationItem>(`/api/spine/conversations/${params.id}`, { title: params.title });
  return data;
}

export async function followEntity(params: { entity_id?: number; type?: string; name?: string }) {
  const { data } = await api.post("/api/spine/follows", params);
  return data;
}

export async function unfollowEntity(entityId: number) {
  await api.delete(`/api/spine/follows/${entityId}`);
}
