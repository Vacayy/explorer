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

// 투자 렌즈 (docs/specs/investor-lens.md) — 원칙 원장에 비춘 종목 판단(프레임, 판정 아님)
export interface LensReading {
  lens_type: string;         // value | trend
  status: string;            // cached | fresh | empty | unavailable | failed
  body: string | null;       // 원칙에 비춘 판독 (마크다운)
  stance: string | null;     // value: 강|중|약 / trend: 초입|진행|성숙|훼손
  signals: string[];         // 역추적용 근거
  created_at: string | null;
  stale: boolean;
}

export interface Quadrant {
  value_axis: string;        // 강|중|약 (가치 확신)
  trend_axis: string;        // 초입|진행|성숙|훼손 (추세 위치)
  cell: string;              // 기회 | 늦은 진입 | 과열 경고 | 회피
  note: string;
}

export interface LensBundle {
  stock_code: string;
  value: LensReading | null;
  trend: LensReading | null;
  quadrant: Quadrant | null; // 두 렌즈 stance로 계산(LLM 0) — 둘 다 있을 때만
}

// 미국 종목 도시에 (docs/specs/us-dossier.md)
export interface UsFundamentals {
  price: number | null;
  market_cap: number | null;
  fwd_pe: number | null;
  trailing_pe: number | null;
  fwd_eps: number | null;
  revenue: number | null;
  net_income: number | null;
  ocf: number | null;
  fcf: number | null;
  capex: number | null;
  earnings_quality: number | null;
  estimates?: Record<string, unknown>;
}

export interface UsDossier {
  ticker: string;
  name: string;
  entity_id: number | null;
  fundamentals: UsFundamentals | null;
  latest_transcript: { id: number; fiscal_year: number; fiscal_period: string; call_date: string } | null;
}

export interface UsListItem {
  ticker: string;
  name: string;
  group_label: string | null;
  value_stance: string | null;
  trend_stance: string | null;
  quadrant_cell: string | null;
  price: number | null;
}
export interface UsGroup {
  label: string;
  items: UsListItem[];
}
export interface UsList {
  groups: UsGroup[];
}
export interface UsMention {
  id: number;
  source_type: string;
  title: string | null;
  url: string | null;
  published_at: string | null;
  excerpt: string | null;
}
export interface UsEdge {
  src: string;
  dst: string;
  rel_type: string;
  direction: string | null;
  confidence: number | null;
  mechanism: string | null;
  self_is_src: boolean;
}
export interface UsNarrativeRef {
  id: number;
  topic: string;
  title: string | null;
}
export interface UsWorldModel {
  entity_id: number | null;
  edges: UsEdge[];
  narratives: UsNarrativeRef[];
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

// 전일 미국시장 거래대금 상위 (홈, TradingView 무키 스크리너 — docs/specs/us-movers.md)
export interface UsMover {
  rank: number; ticker: string; name: string;
  close: number | null; volume: number | null; dollar_volume: number | null;
  exchange: string | null; is_adr: boolean;
}
export interface UsMoversResponse {
  status: "ok" | "stale" | "error";
  source: string; fetched_at: string | null; error: string | null;
  items: UsMover[];
}

// 어젯밤 미국장 브리핑 (홈 상단, docs/specs/us-briefing.md)
export interface UsHeadline {
  title: string; publisher: string | null; published_at: string | null;
  url: string | null; summary: string | null;
}
export interface UsMoverBrief {
  rank: number; ticker: string; name: string;
  dollar_volume: number | null; change_pct: number | null;
  sector: string | null; industry: string | null; cluster: string;
  is_adr: boolean; is_new: boolean;
  coverage: "covered" | "uncovered"; entity_id: number | null;
  mentions_3d: number; narrative: string | null; flags: string[];
  headlines: UsHeadline[];
}
export interface UsCluster {
  label: string; n: number; dollar_volume: number; share_pct: number;
  median_change: number; has_new: boolean; tickers: string[];
}
/** 4섹션 종합 (D-112). 구 스키마(mood 단일)는 백엔드가 issues로 승계해 내려준다. */
export interface UsBriefingSynthesis {
  index_summary: string;   // ① 지수 마감
  drivers: string;         // ② 시장을 움직인 요인
  issues: string;          // ③ 거래대금 기반 이슈
  flow: string;            // ④ 시계열 흐름
  study_candidates: string[]; share_candidates: string[];
}
export interface UsIndexMove { name: string; close: number; change_pct: number }
export interface UsIndexBlock { as_of: string | null; items: UsIndexMove[] }
export interface UsMacroItem { name: string; value: number; change_pct: number; group: string | null }
export interface UsMacroSignal { as_of: string | null; signal: string | null; headline: string | null }
export interface UsMacroBlock {
  as_of: string | null; items: UsMacroItem[]; lookback: string | null;
  signal: UsMacroSignal | null; degraded: string[];
}
export interface UsFlowPoint { date: string; share_pct: number }
export interface UsFlowSector { label: string; series: UsFlowPoint[] }
export interface UsFlowBlock { dates: string[]; sectors: UsFlowSector[] }
export interface UsBriefingListItem { trade_date: string; model: string | null; created_at: string | null }
export interface UsMarketTheme { name: string; count: number }
export interface UsMarketDoc {
  id: number; source_type: string; title: string | null;
  published_at: string | null; excerpt: string | null;
}
export interface UsBriefing {
  status: "ok" | "stale" | "partial" | "error";
  trade_date: string | null; fetched_at: string | null; error: string | null;
  stale_days: number | null;                 // 스냅샷 경과일 — 며칠 묵었나 (D-112)
  clusters: UsCluster[]; idiosyncratic: UsMoverBrief[]; movers: UsMoverBrief[];
  market_themes: UsMarketTheme[]; market_docs: UsMarketDoc[];
  indices: UsIndexBlock; macro: UsMacroBlock; flow: UsFlowBlock;   // D-112
  synthesis: UsBriefingSynthesis | null;
}

// 매크로·유동성 트래킹 (홈, docs/specs/macro.md)
export interface MacroIndicator {
  key: string; label: string; group: string; group_label: string;
  fmt: "pct" | "num" | "usd" | "trillion_b";
  value: number; change_pct: number | null; series: number[];
}
export interface MacroInterpretation { stance: string; comment: string }
export interface MacroSignal { signal: "green" | "yellow" | "red"; headline: string; comment: string }
export interface MacroData {
  as_of: string | null; items: MacroIndicator[]; degraded: string[];
  interpretation: MacroInterpretation | null;   // 결정적 폴백
  signal: MacroSignal | null;                    // 신호등 산문(sonnet)
  fred_enabled: boolean;
}

/* ── 국장 거래대금 상위 (D-108) — 미국장의 국장 대응물, LLM 종합 없음 ── */
export interface KrMoverItem {
  rank: number; stock_code: string; name: string; market: string | null;
  close: number | null; volume: number | null; value_traded: number | null;
  change_pct: number | null; sector: string | null; market_cap: number | null;
  is_new: boolean; flags: string[];
}
export interface KrCluster {
  label: string; n: number; value_traded: number; share_pct: number;
  median_change: number; has_new: boolean; codes: string[]; names: string[];
}
export interface KrMovers {
  status: string; source: string; trade_date: string | null;
  fetched_at: string | null; error: string | null;
  items: KrMoverItem[]; clusters: KrCluster[]; idiosyncratic: KrMoverItem[];
}
