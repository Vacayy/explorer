export interface Company {
  corp_code: string;
  corp_name: string;
  stock_code: string | null;
  market: string | null;
  sector: string | null;
}

export interface FinancialRow {
  account_nm: string;
  values: (string | null)[];
  yoy: (number | null)[];
}

export interface KeyMetric {
  values: (string | null)[];
  yoy: (number | null)[];
  account_nm: string;
}

export interface FinancialResponse {
  periods: string[];
  rows: FinancialRow[];
  key_metrics?: Record<string, KeyMetric>;
  sj_div: string;
  fs_div: string;
  period_type: string;
}

export interface DisclosureItem {
  rcp_no: string;
  corp_name: string | null;
  report_nm: string | null;
  rcept_dt: string | null;
  flr_nm: string | null;
  rm: string | null;
  dart_url: string | null;
}

export interface IRNote {
  id: number;
  corp_code: string;
  title: string;
  content: string | null;
  note_date: string;
  memo_type: string;
  created_at: string;
  updated_at: string;
}

export interface StockPriceItem {
  trade_date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  market_cap: number | null;
}

export interface ValuationItem {
  trade_date: string;
  close: number | null;
  bps: number | null;
  per: number | null;
  pbr: number | null;
  eps: number | null;
  div_yield: number | null;
}

export interface ValuationResponse {
  items: ValuationItem[];
  pbr_bands: Record<string, (number | null)[]> | null;
}

export interface IndustryGroup {
  id: number;
  name: string;
  description: string | null;
}

export interface IndustryMember {
  id: number;
  stock_code: string;
  category: string;
  corp_name: string;
  latest_close: number | null;
  latest_market_cap: number | null;
  per: number | null;
  pbr: number | null;
  op_margin: number | null;
  roe: number | null;
  revenue_growth: number | null;
  op_profit_growth: number | null;
}

export interface IndustryDetail {
  group: IndustryGroup;
  members: IndustryMember[];
}

export interface IndustryCandidate {
  stock_code: string;
  entity_id: number;
  name: string;
  rs_short: number | null;
  rs_prev: number | null;
  per: number | null;
  pbr: number | null;
  market_cap: number | null;
  pos_52w: number | null;
  co_mentions: number | null;
  relevance: number;
}

export interface BusinessSegment {
  id: number;
  corp_code: string;
  bsns_year: number;
  segment_type: string;
  segment_name: string;
  revenue: number | null;
  ratio: number | null;
}

export interface SignalItem {
  type: "disclosure" | "insider" | "contract";
  stock_code: string;
  corp_name: string | null;
  title: string | null;
  date: string;
  url: string | null;
  in_watchlist: boolean;
}

export interface CatalystItem {
  id: number;
  stock_code: string | null;
  corp_code: string | null;
  corp_name: string | null;
  event_type: string;
  event_date: string;
  title: string;
  description: string | null;
  created_at: string;
}

export interface WatchlistItem {
  id: number;
  stock_code: string;
  corp_code: string;
  corp_name: string;
  conviction: number;
  target_price: number | null;
  thesis: string | null;
  created_at: string;
  updated_at: string;
  latest_close: number | null;
  latest_market_cap: number | null;
  gap_pct: number | null;
}

// ---------- Spine (그래프 척추) API ----------

export interface EntityTag {
  entity_id: number;
  type: string;          // company | sector | theme
  name: string;
  aliases: string | null; // company면 종목코드
  link_type: string;     // stock | industry | topic | mention
  confidence: number | null;
}

export interface FeedDocument {
  id: number;
  source_type: string;   // blog | telegram
  title: string;
  url: string;
  published_at: string;
  summary: string | null;
  channel: string | null;    // 출처 채널/블로그 이름
  channel_kind: string | null; // telegram | blog — 소스 도시에 링크용
  channel_key: string | null;  // channel_name | blog url
  content: string | null;    // 전문 (markdown)
  images: string[];          // /media 상대경로
  enrich_model: string | null;
  entities: EntityTag[];
}

export interface SpineFeedResponse {
  items: FeedDocument[];
  total: number;
  page: number;
  size: number;
  as_of: string;
}

// 종목 AI 브리프 (P2-1, docs/specs/product-v3.md §3)
export interface StockBrief {
  status: string;            // fresh | cached | empty | unavailable | failed
  brief: string | null;
  thesis_check: string | null;  // 내 논지 vs 새 증거 충돌·지지
  revision_call: { direction: "up" | "down" | "hold"; rationale: string | null } | null;  // 추정치 방향 콜 (실측 대조용 기록)
  created_at: string | null;
  stale: boolean;
  evidence?: string[];       // 근거 재료 인벤토리 (다이제스트·신호·공시·일정·논지)
  has_thesis?: boolean;      // false면 논지 등록 유도 표시
  thesis?: string | null;    // 논지 원문 (불변 — AI는 점검만)
}

// 대화 (P2-0/P2-1)
export interface ConversationItem {
  id: number;
  title: string | null;
  channel: string;           // web | telegram
  anchor_entity_id: number | null;
  message_count: number;
  updated_at: string;
}

export interface ConversationDetail {
  id: number;
  title: string | null;
  channel: string;
  messages: {
    id: number;
    role: string;
    content: string;
    citations: { n: number; doc_id: number; title: string }[] | null;
    gaps: { type: string; note: string }[] | null;
    model: string | null;
    created_at: string;
  }[];
}

// 소스 도시에 (docs/specs/source-dossier.md)
export interface DossierSummary {
  status: string;            // fresh | cached | empty | unavailable | failed
  digest: string | null;
  insights: string | null;
  created_at: string | null;
  doc_count: number;
}

export interface SourceDossier {
  kind: string;              // telegram | blog
  key: string;
  name: string;
  author: string | null;
  is_active: boolean;
  total_docs: number;
  first_doc_at: string | null;
  last_doc_at: string | null;
  docs_7d: number;
  summary: DossierSummary | null;
  summary_stale: boolean;
  top_entities: { entity_id: number; name: string; link_type: string; aliases: string | null; count: number }[];
  recent_docs: { id: number; title: string; published_at: string | null }[];
}

export interface SpineSignal {
  id: number;
  signal_type: string;
  entity_id: number;
  entity_name: string;
  stock_code: string | null;
  date: string;
  payload: {
    // mention_surge
    count_7d?: number;
    baseline_7d?: number;
    keywords?: string[];
    docs?: { id?: number; title: string; url: string }[];
    // high_52w
    close?: number;
    high?: number;
    prior_high_52w?: number;
    breakout_pct?: number;
    // neglect
    per?: number;
    roe?: number;
    market_cap?: number;
    market?: string;
    window_days?: number;
    // consensus_extreme (진자)
    direction?: "optimism" | "pessimism" | "up" | "down";
    pos?: number;
    neg?: number;
    ratio?: number;
    // volume_spike (거래량이 터진 날)
    volume?: number;
    avg_vol_60d?: number;
    change_pct?: number;
    // quadrant_gap (주가×관측 괴리)
    quadrant?: "C" | "D_RISK";
    return_3m?: number;
    // theme_surge (주목 주제)
    recent?: number;
    share_pct?: number;
    share_delta_pp?: number;
    is_new?: boolean;
  };
  interpretation: string | null;
  interpretation_model: string | null;
}

export interface SpineSignalsResponse {
  items: SpineSignal[];
  as_of: string;
}

export interface CalendarEvent {
  id: number;
  stock_code: string | null;
  corp_name: string | null;
  event_type: string;
  event_date: string;
  title: string;
  in_watchlist: boolean;
}

export interface HomeFollow {
  entity_id: number;
  type: string;
  name: string;
}

export interface WatchlistUpdate {
  kind: "document" | "signal";
  entity_type: string;         // company | sector | theme
  entity_id: number | null;
  doc_id: number | null;       // 내부 디테일(/doc/:id) 링크용
  stock_code: string | null;
  corp_name: string;           // 표시명
  occurred_at: string;
  title: string;
  url: string | null;
  source_type: string | null;
  signal_type: string | null;
}

export interface BriefItem {
  kind: "insight" | "action" | "signal" | string;
  text: string;
  to: string;
}

export interface HomeResponse {
  briefing: BriefItem[];
  calendar: CalendarEvent[];
  follows: HomeFollow[];
  watchlist_updates: WatchlistUpdate[];
  market_highlights: SpineSignal[];
  watchlist_empty: boolean;
  as_of: string;
}

export interface AskCitation {
  n: number;
  doc_id: number;
  title: string;
  url: string;
  source_type: string;
  published_at: string;
}

export interface AskGap {
  type: "unsupported" | "contradiction" | "stale" | "missing" | string;
  note: string;
}

export interface AskResponse {
  answer: string | null;
  citations: AskCitation[];
  gaps: AskGap[];
  model: string | null;
  conversation_id: number | null;  // 적재된 스레드 (P2-0)
  as_of: string;
}

/* ── 시장 국면 (market regime, D-076) ── */
export type PostureColor = "favorable" | "caution" | "risk" | "neutral";
/** [YYYY-MM-DD, value] 튜플 시계열 (스파크라인) */
export type MarketSeries = [string, number][];

/** 추세 게이트 = 오실레이터의 20 EMA (가격 EMA 아님) */
export interface MarketPostureUS {
  posture: string;
  posture_color: PostureColor;
  reason: string;
  fear_greed: { score: number; zone: string } | null;
  vix: { value: number; band: string } | null;
  trend: { ema: number | null; dir: string };   // F&G의 20 EMA
  series: { osc: MarketSeries; osc_ema: MarketSeries; vix: MarketSeries };
}

export interface MarketPostureKR {
  posture: string;
  posture_color: PostureColor;
  reason: string;
  oscillator: { metric: string; value: number | null; zone: string };
  trend: { ema: number | null; dir: string };    // RSI14의 20 EMA
  volatility: { metric: string; value: number | null; band: string } | null;
  series: { osc: MarketSeries; osc_ema: MarketSeries; vol: MarketSeries };
}

export interface MarketRegime {
  as_of: string | null;
  headline: string;
  kr: MarketPostureKR | null;
  us: MarketPostureUS | null;
  degraded: string[];
}

/* ── 논지 감사 (thesis audit) — thesis를 인과그래프에 대질한 read-only 델타 ── */
export type ThesisVerdict = "aligned" | "contested" | "challenged" | "novel";
export type ThesisRole = "consensus" | "shift" | "catalyst" | "causal" | "synthesis";
export type EdgeStance = "support" | "contradict" | "context";

export interface ThesisEdge {
  id: number; src: string; dst: string; rel_type: string;
  effect_direction: string | null; effect_strength: string | null;
  corroborated_by: number; confidence: number; mechanism: string | null;
  created_at: string | null; reference_period: string | null; stance: EdgeStance;
}
export interface ThesisNarrative {
  topic: string; version: number; title: string | null;
  category: string | null; drift_summary: string | null; created_at: string;
}
export interface ThesisTemporal {
  monthly: { ym: string; count: number }[]; spiking: boolean;
  latest: { ym: string; count: number } | null; prev: { ym: string; count: number } | null;
}
/* 진자 (stage 3) — salience × conviction 직교 축: 선반영/소외 기회 */
export type ThesisQuadrant = "priced_in" | "overhyped" | "hidden_edge" | "noise";
export interface ThesisPendulum {
  salience: number; conviction: number; quadrant: ThesisQuadrant;
  pace_layer: string; independent: number; refute: number;
}
export interface ThesisClaim {
  claim: string; role: ThesisRole; anchor_terms: string[];
  verdict: ThesisVerdict; spiking: boolean; pendulum?: ThesisPendulum;
  edges: ThesisEdge[]; narratives: ThesisNarrative[]; temporal: ThesisTemporal;
}
export interface ThesisAudit {
  id: number; created_at: string; thesis_text: string;
  claims: ThesisClaim[]; n_claims: number;
}
export interface ThesisAuditListItem {
  id: number; created_at: string; preview: string; n_claims: number;
}
