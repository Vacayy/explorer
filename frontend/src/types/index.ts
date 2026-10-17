export interface Company {
  corp_code: string;
  corp_name: string;
  stock_code: string | null;
  market: string | null;
  sector: string | null;
}

export type RecentCompanySearch = Pick<Company, 'corp_name'> & { stock_code: string };

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

/** 최근 N거래일 시세 스냅샷 — stock_prices 테이블만(16:10 스냅샷), 대화 차트 카드용 */
export interface PriceSnapshot {
  stock_code: string;
  name: string;
  items: { trade_date: string; open: number | null; high: number | null; low: number | null; close: number | null; volume: number | null }[];
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
  /** 멤버가 속한 산업 맵 대분류(sector_map) 상위 3 — 두 섹터 체계를 잇는 링크용 */
  map_groups?: { name: string; members: number }[];
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
  digest_status?: string | null;
  digest_error?: string | null;
  video_digest?: string | null;
  transcript?: string | null;
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

// 투자 렌즈 (docs/private/specs/investor-lens.md) — 원칙 원장에 비춘 종목 판단(프레임, 판정 아님)
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

/** 답변 경로 — 라우팅·도구 로그 (D-131, chat_messages.route_json). "왜 이 답이 나왔나" 1클릭. */
export interface ChatRoute {
  intent: string | null;
  standalone_question: string | null;
  entities: { name: string; kind?: string }[] | null;
  lens: string | null;
  answer_style: string | null;
  tools: { name: string; args?: Record<string, unknown>; n?: number; note?: string | null; ms?: number; error?: string }[];
  evidence_n: number;
  timings_ms: { route?: number; review?: number; synth?: number };
  model: string | null;
  steps?: string[] | null;                                   // 과정 자연어 서술 (코드 생성, D-134)
  process?: string[] | null;                                 // 종합 모델의 판단 메모 (META.process)
  review?: { enough: boolean; reason?: string; added?: string[]; skipped?: boolean } | null;
  /** 후속 질문 제안 (D-145) — 종합 META에 동승, 추가 LLM 콜 0 */
  follow_ups?: { kind: string; question: string }[] | null;
}

export interface ConversationDetail {
  study?: {id:number; title:string} | null;
  study_project?: {id:number; title:string} | null;
  id: number;
  title: string | null;
  channel: string;
  attached_documents?: { id: number; title: string | null }[]
  messages: {
    id: number;
    role: string;
    content: string;
    citations: { n: number; doc_id: number | null; title: string; href?: string | null; kind?: string }[] | null;
    gaps: { type: string; note: string }[] | null;
    model: string | null;
    route?: ChatRoute | null;
    created_at: string;
  }[];
}
export type ChatMessage = ConversationDetail["messages"][number];

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
    // call_momentum (실적 발언 모멘텀, 미국 기업)
    ticker?: string;
    score?: number;
    drivers?: { name: string; status?: string; magnitude?: string; quote?: string; verified?: boolean }[];
  };
  interpretation: string | null;
  interpretation_model: string | null;
}

export interface SpineSignalsResponse {
  items: SpineSignal[];
  as_of: string;
}

/** GET /api/spine/sector-map — 18 대분류 RS 사분면. trail = 1·2·3주 전 위치 */
export interface SectorTrailPoint { weeks_ago: number; rs_long: number | null; rs_short: number | null }
export interface SectorGroup {
  name: string; market_cap: number; stocks: number
  rs_long: number | null; rs_short: number | null; chg_5d: number; trail: SectorTrailPoint[]
}
export interface SectorMap { as_of: string | null; groups: SectorGroup[] }

/** GET /api/spine/signals/summary — 유형별 최신일 건수·상위 3. as_of = 신호 최신일 */
export interface SignalsSummaryType {
  type: string;
  latest_date: string;
  count_latest: number;
  count_window: number;
  top: { entity_id: number; name: string; stock_code: string | null; ticker: string | null }[];
}
export interface SignalsSummary {
  as_of: string | null;
  types: SignalsSummaryType[];
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

/** 근거 인용 — 문서뿐 아니라 내러티브·인과 엣지·시세 등 시스템 산출물도 근거(D-131). 링크는 href 우선. */
export interface AskCitation {
  n: number;
  kind: string;                 // doc | narrative | edges | knowledge | question | lens | quote | regime | briefing …
  doc_id: number | null;
  title: string;
  href: string | null;
  published_at: string | null;
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
/** 매크로 문단 출처 표식 `[n]`의 대상 (D-206). */
export interface UsBriefingSource {
  n: number; kind: "telegram" | "news" | "official"; publisher: string;
  title: string | null; url: string | null; doc_id: number | null; published_at: string | null;
}
/** 2문단 종합 (D-206): 매크로 + 거래대금 기업 이슈. 구 스키마(mood 단일)는 백엔드가 issues로 승계해 내려준다. */
export interface UsBriefingSynthesis {
  index_summary: string;   // D-206 이전 행 호환(새 종합은 빈 값)
  drivers: string;         // 매크로 — `[n]` 출처 표식 포함
  issues: string;          // 거래대금 기반 기업 이슈
  key_points?: string[]; study_candidates: string[]; share_candidates: string[];
  sources: UsBriefingSource[];
  source_gaps: string[];   // 빠진 재료(피드 수집 실패 등)
}
export interface UsIndexMove { name: string; close: number; change_pct: number }
export interface UsIndexBlock { as_of: string | null; items: UsIndexMove[] }
export interface UsMacroItem { name: string; value: number; change_pct: number; group: string | null }
export interface UsMacroSignal { as_of: string | null; signal: string | null; headline: string | null }
export interface UsMacroBlock {
  as_of: string | null; items: UsMacroItem[]; lookback: string | null;
  signal: UsMacroSignal | null; degraded: string[];
}
/** '소스 관리' — 브리핑 재료 목록과 최근 수집 상태 (D-206 후속). */
export interface UsBriefingSourceItem {
  name: string; detail: string | null; url: string | null;
  last_seen: string | null;        // ISO UTC 또는 날짜(YYYY-MM-DD)
  recent_count: number | null;     // 최근 24시간 자료 수
  status: "ok" | "quiet" | "off";
}
export interface UsBriefingSourceGroup { key: string; label: string; used_for: string; items: UsBriefingSourceItem[] }
export interface UsBriefingSources { groups: UsBriefingSourceGroup[] }
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
  expected_session?: string | null;          // 마지막으로 마감된 미국 정규장(ET, 공휴일 미반영) — trade_date와 다르면 어젯밤 미반영
  synthesized_at?: string | null;            // 종합 저장 시각(UTC)
  last_run?: { status: string; summary: string | null; ran_at: string } | null   // 정기 생성(06:30 KST) 마지막 실행
  clusters: UsCluster[]; idiosyncratic: UsMoverBrief[]; movers: UsMoverBrief[];
  market_themes: UsMarketTheme[]; market_docs: UsMarketDoc[];
  indices: UsIndexBlock; macro: UsMacroBlock;   // D-112
  synthesis: UsBriefingSynthesis | null;
}

// 매크로·유동성 트래킹 (홈, docs/specs/macro.md)
export interface MacroIndicator {
  key: string; label: string; group: string; group_label: string; as_of?: string;
  fmt: "pct" | "num" | "usd" | "trillion_b";
  value: number; change_pct: number | null; series: number[];
  dated_series?: [string, number][];
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
  briefing?: { stock_code: string; name: string; rank: number; parent_company_context: boolean;
    documents: { doc_id: number; title: string | null; source_type: string; published_at: string | null; excerpt: string | null; excerpt_kind: string | null }[] }[];
}

// Home and /feed share the same stored-update contract (docs/specs/home-feed.md).
export interface TimelineItem {
  id: string
  kind: 'source' | 'company' | 'person' | 'transcript' | 'trade' | 'narrative' | 'report' | 'scenario'
  title: string
  body: string
  occurred_at: string
  time_label: string
  subject: string
  period: string | null
  evidence_count: number | null
  ai_generated: boolean
  to: string
  document: FeedDocument | null
  links: { label: string; to: string }[]
}

export interface TimelineResponse {
  items: TimelineItem[]
  page: number
  size: number
  has_more: boolean
  until: string
  as_of: string
}


export interface TimelineChannel {
  id: string
  name: string
  platform: 'telegram' | 'blog' | 'youtube' | 'system'
  count: number
  /** 읽음 표시(read_until, 없으면 기준선) 이후 게시물 수 (D-200) */
  unread: number
  latest_at: string | null
  preview: string
}
export interface TimelineChannelsResponse {
  total_unread: number
  items: TimelineChannel[]
  total: number
  until: string
}
export type StudyIntent = 'explain' | 'critique' | 'related';
export type StudyTool = 'read' | 'highlight' | 'comment' | StudyIntent;
export interface StudyActionRequest {
  intent: StudyIntent;
  selection?: { start: number; end: number; exact: string };
  annotation?: { id: number; revision: number };
  parent_id?: number;
  retry_of?: number;
  question?: string;
  research?: 'auto' | 'web';
}
export interface StudyAction {
  id: number;
  study_id: number;
  annotation_id: number;
  annotation_revision: number;
  intent: StudyIntent;
  status: 'queued' | 'running' | 'complete' | 'error' | 'cancelled';
  question: string;
  parent_id: number | null;
  retry_of: number | null;
  queue_position: number;
  created_at: string;
  started_at: string | null;
  error: string | null;
  prompt_version: string;
  result: {
    answer?: string;
    citations?: ChatMessage['citations'];
    model?: string;
    research?: {
      intent: string;
      notes?: string[];
      results: { title: string; href?: string | null; date?: string | null; kind?: string; doc_id?: number; text?: string; read_scope?: string }[];
    };
  } | null;
}

// 종목 묶음·기술적 감시 (docs/specs/portfolio-watch.md, D-185)
export type StockGroupKind = 'watch' | 'portfolio';
export interface WatchRule {
  id: number; stock_code: string | null; strategy_id: string; label: string; params: Record<string, unknown>;
  within_days: number; source_strategy_id: string | null; source_version: number | null;
}
export interface WatchRuleInput { strategy_id: string; params?: Record<string, unknown>; within_days?: number; source_strategy_id?: string | null; source_version?: number | null }
export interface GroupSignal {
  stock_code: string; name?: string; rule_id: number; as_of: string; strategy_id: string; label: string;
  params: Record<string, unknown>; value: number | null; reference: number | null; signal_date: string | null;
}
export interface StockGroupMember {
  id: number; group_id: number; stock_code: string; name: string; market: string | null;
  bought_at: string | null;
  conviction: number | null; target_price: number | null; thesis: string | null; created_at: string;
  close: number | null; change_pct: number | null; market_cap: number | null; price_date: string | null;
  rule_count: number; signals: { rule_id: number; strategy_id: string; label: string; value: number | null; reference: number | null; signal_date: string | null }[];
  unavailable: number;
}
export interface StockGroupSummary {
  id: number; name: string; kind: StockGroupKind; note: string; created_at: string; updated_at: string;
  member_count: number; rule_count: number; last_as_of: string | null; today_signals: number;
}
export interface StockGroupList { items: StockGroupSummary[]; latest_trade_date: string | null }
export interface StockGroupDetail {
  id: number; name: string; kind: StockGroupKind; note: string; created_at: string; updated_at: string;
  members: StockGroupMember[]; rules: { default: WatchRule[]; members: Record<string, WatchRule[]> };
  last_as_of: string | null; latest_trade_date: string | null; evaluation_pending: boolean; today_signals: number;
}
export interface StrategyCatalogItem {
  id: string; label: string; category: string; timeframe?: string; description?: string; formula?: string;
  parameters: Record<string, { type: 'integer' | 'number' | 'string'; label?: string; min?: number; max?: number; options?: string[] }>;
  defaults: Record<string, unknown>;
}

// 웹 조사 기업 개요 보고서 (docs/specs/company-research.md §웹 조사 레인, D-188)
export interface CompanyWebSource { id: number; url: string; title: string; publisher: string; published_at: string | null; kind: 'filing' | 'ir' | 'news' | 'report' | 'other'; excerpt: string; fetched: boolean }
export interface CompanyWebProfile {
  id: number; stock_code: string; version: number; created_at: string; model: string | null; cost_usd: number | null; reason: string | null; source_count: number;
  overview: string;
  business_lines: { name: string; description: string; share_pct: number | null; source_ids: number[] }[];
  products_customers: { text: string; source_ids: number[] }[];
  competitors: string[];
  drivers: { text: string; source_ids: number[] }[];
  risks: { text: string; source_ids: number[] }[];
  recent_events: { date: string | null; title: string; source_ids: number[] }[];
  sources: CompanyWebSource[];
  gaps: string[];
  official_report?: { rcept_no: string; report_nm: string; rcept_dt: string | null; url: string } | null;
}

// Home Risk — dated observations and an explicitly experimental joint condition.
export interface RiskIndicator {
  key: string
  label: string
  unit: string
  source: string
  source_url: string
  value: number | null
  as_of: string | null
  fetched_at: string | null
  attempted_at: string | null
  error: string | null
  quality: 'fresh' | 'missing' | 'stale' | 'error'
  lag_days: number | null
  points: [string, number][]
  change_5: number | null
  change_20: number | null
}
export interface RiskResponse {
  items: RiskIndicator[]
  signal: {
    status: 'unavailable' | 'joint' | 'watch' | 'credit' | 'rates' | 'clear'
    label: string
    as_of: string | null
    rate_change_bp: number | null
    credit_change_bp: number | null
    consecutive: number
    common_observations: number
    rule_version: string
    reason: string
  }
  expected_date: string
  generated_at: string
  calendar_note: string
  empty: boolean
}
export interface RiskSnapshotResponse {
  busy: boolean
  results: { key: string; status: 'cached' | 'updated' | 'error'; rows: number; error: string | null }[]
}

/* ---------- 포트폴리오 (D-212) — 비율·가격만, 원화 금액·수량 없음 ---------- */
export interface PortfolioHolding {
  code: string
  name: string
  weight_pct: number | null
  return_pct: number | null
  day_change_pct: number | null
  avg_price: number
  last_close: number | null
  last_date: string | null
  entry_date: string
  price_source: 'live' | 'close'   // live = 장중 시세(30분 갱신)
  quoted_at: string | null
}
/** 매도 한 건의 실현 결과 — 비율·가격만 */
export interface PortfolioClosedTrade {
  code: string; name: string; entry_date: string; sell_date: string
  avg_price: number; sell_price: number; return_pct: number | null; holding_days: number | null
  full: boolean   // 이 매도로 전량 청산
}
export interface PortfolioSummary {
  as_of: string | null
  total_return_pct: number | null
  day_return_pct: number | null
  cash_weight_pct: number | null
  holdings: PortfolioHolding[]
  quoted_at: string | null
  realized_pct: number | null     // 실현 손익 ÷ 원금(순입금)
  unrealized_pct: number | null   // 미실현 손익 ÷ 원금
  closed: PortfolioClosedTrade[]  // 최근 매도부터
}
/** 운용 원칙(D-227) — 수치 규칙 하나 */
export interface PrincipleRule { type: string; params: Record<string, number>; summary?: string | null }
export interface PortfolioPrinciple { id: number; text: string; created_at: string; rules: PrincipleRule[]; notes: string[] }  // notes = 대화에서 참고하는 원칙(시스템 정리·사용자 확인)
export interface PrincipleParse { rules: PrincipleRule[]; unparsed: string[] }
/** 지금 어기고 있는 규칙 — 문장은 종목명·비율·한도만. alerted_since(UTC)가 없으면 다음 점검에서 알림 */
export interface PrincipleViolation { key: string; principle_id: number; rule: string; message: string; alerted_since: string | null }
export interface PrincipleState { as_of: string | null; rules: number; items: PrincipleViolation[] }
/** 보낸 텔레그램 알림 한 건 — 유형·종목·구간·시각(KST)만 */
export interface PortfolioAlert { kind: 'day' | 'avg' | 'tech' | 'disc' | 'summary' | string; label: string; code: string | null; name: string | null; date: string | null; sent_at: string; url: string | null }
/** 묶음 종목의 최신 1D 요약 */
export interface GroupDigest { code: string; name: string; date: string; lead: string | null; insights: string | null; docs: number | null }
export interface PortfolioHistoryPoint { date: string; cum_return_pct: number; day_return_pct: number }
export type PortfolioTxKind = 'buy' | 'sell' | 'deposit' | 'withdraw'
export interface PortfolioTransaction { id: number; trade_date: string; kind: PortfolioTxKind; stock_code: string | null; name: string | null; price: number | null }
export interface PortfolioTxInput { trade_date: string; kind: PortfolioTxKind; stock_code?: string; amount?: number; price?: number; fund_shortfall?: boolean; sell_all?: boolean }
export interface ExposureDriver {
  key: string; name: string; type: string
  exposure_pct: number; holdings: string[]
  sources: ('graph' | 'comention' | 'chain')[]
  direction: string | null; confidence: number | null; hops: number | null
}
export interface PortfolioExposure {
  drivers: ExposureDriver[]
  coverage: Record<string, { graph: number; comention: number; chain: string | null; stage: string | null }>
  held: string[]
}
export interface PortfolioEvent {
  date: string
  kind: 'ir' | 'earnings_notice' | 'agm' | 'earnings_est' | 'report_deadline' | 'us_earnings' | string
  title: string; code: string | null; name: string | null
  estimated: boolean; url: string | null; basis: string | null
}
export interface HoldingFlow {
  code: string; name: string
  series: { date: string; n: number; pos: number; neg: number }[]
  today: number; avg7: number; surge: boolean; tone_shift: boolean
  neg_today_pct: number | null; neg_prev_pct: number
  digest: { date: string; insights: string | null; lead: string | null; docs: number } | null
}
export type QuestionVerdict = 'leaning_yes' | 'leaning_no' | 'mixed' | 'unknown' | null
export interface HoldingThesis {
  id: number; text: string; lead: QuestionVerdict; confirm: QuestionVerdict; divergence: string | null; summary: string | null
  sub_questions: { text: string; falsifier: string | null; verdict: QuestionVerdict }[]
  warnings: string[]
  judged_at: string | null   // 마지막 판정 시각(UTC)
  judging: boolean           // 판정 엔진이 꺼져 있으면 false — 판정·알림이 judged_at에서 멈춤
}

/** 관심 종목 이유 감시(D-227) — 보유 논지와 같은 판정, 신호는 지지·약화 양쪽 */
export type WatchReason = Omit<HoldingThesis, 'warnings'> & { signals: string[] }

/* ---------- 실적 발언 모멘텀 (D-217) ---------- */
export interface CallDriver { name: string; type: string; status: 'new' | 'accelerating' | 'steady' | 'decelerating'; magnitude?: string; quote: string; source: string }
export interface CallGuidance { metric: string; direction: 'raised' | 'lowered' | 'maintained' | 'initiated'; quote: string; source: string }
export interface CallMomentumCandidate {
  ticker: string; name: string | null; event_date: string; score: number; first_candidate_at: string | null
  drivers: CallDriver[]; guidance: CallGuidance[]; tone: number | null; prev_tone: number | null; sources: string[]; qa_focus: string[]
}
export interface CallMomentumSeason { key: string; label: string; start: string }
export interface CallMomentum {
  season: CallMomentumSeason & { reported: number }
  candidates: CallMomentumCandidate[]          // 이번 실적 시즌만
  history: (CallMomentumSeason & { candidates: CallMomentumCandidate[] })[]
  coverage: { universe: number; with_releases: number; with_transcripts: number; extracted_docs: number; failed_docs: number; comparable: number }
  sec_configured: boolean
  as_of?: string | null                        // 마지막 판정 시각(UTC, call_momentum.computed_at)
}

/** GET /api/spine/transcript/recent — 최근 받은 컨콜(수집 시각순) */
export interface RecentCall {
  transcript_id: number; ticker: string; company_name: string | null; fiscal_year: number; fiscal_period: string
  cy: string | null; call_date: string | null; provider: string | null; fetched_at: string | null; has_digest: boolean
}

/** 문서 디테일 '관련 문서' — GET /api/spine/doc/{id}/related (D-221) */
export interface RelatedDoc {
  id: number
  source_type: string
  title: string | null
  published_at: string | null
  channel: string | null
  similarity: number
  reasons: string[]   // 겹치는 종목·인물·산업
}

/** 문서 상세 '논점별 관련 자료' — GET /api/spine/doc/{id}/claims (D-233) */
export interface ClaimRelated {
  id: number
  source_type: string
  title: string | null
  published_at: string | null
  channel: string | null
  quote: string | null   // 찾은 대목의 원문 문장 (LLM 작성 아님)
  score: number
}

export interface DocClaim {
  claim: string          // LLM이 뽑은 논점(해석)
  related: ClaimRelated[]
}

export interface DocClaims {
  status: 'none' | 'running' | 'ok' | 'failed' | 'skipped'
  error: string | null
  claims: DocClaim[]
}

/* ---------- 회사채 스프레드 (D-230) ---------- */
export interface CreditRow {
  ticker: string; name: string; group: string; bond: string | null; rating: string | null; hy: boolean
  source: string | null   // TRACE | 유럽 거래소
  ytm: number | null; treasury: number | null; spread_bp: number | null
  chg_1m: number | null; chg_3m: number | null; chg_1y: number | null
  pd_pct: number | null   // 5년 누적 부도확률(위험중립 근사, 회수율 40%)
  last_date: string | null
}
export interface CreditTable { configured: boolean; as_of: string | null; groups: { key: string; label: string }[]; rows: CreditRow[] }
export interface CreditHistory { tickers: string[]; points: Record<string, number | string | null>[] }

/* ---------- 수출입 (trade-follow.md, D-140) ---------- */
export type TradeFlag = 'surge' | 'plunge' | 'new' | 'none'
export interface TradeFollowRow {
  hs_code: string; item_name: string; group_label: string | null
  latest_period: string | null; latest_export: number | null; yoy_pct: number | null
  z: number | null; flag: TradeFlag | null; reason: string | null
  contribution: number | null   // 0~1 — 이번 달 전년 동월 대비 증감액 기여도(최상위 품목 합 기준)
  nested_in: string | null      // 이 품목을 포함하는 상위 팔로우 HS — 합계에서 제외
}
export interface TradeHighlightRow {
  hs_code: string; item_name: string; group_label: string | null; value: number | null
  yoy: number | null; z: number | null; flag: TradeFlag; reason: string | null
  contribution: number | null; nested_in: string | null
}
export interface TradeHighlights {
  period: string | null; total_usd: number
  surge: TradeHighlightRow[]; plunge: TradeHighlightRow[]   // 상위 limit개만
  groups: { group_label: string; count: number; value: number; surge: number; plunge: number }[]   // 판정 수는 전 품목 기준
}
export interface TradeStockItem {
  hs_code: string; item_name: string; rel: string | null; period: string | null
  yoy_pct: number | null; flag: TradeFlag | null; reason: string | null
}

/* ---------- 기업활동 (spine_actions) ---------- */
export type ActionKind = 'all' | 'original' | 'correction'
export type MyGroup = '보유' | '관심'
export interface CorporateAction {
  id: number; rcp_no: string; corp_name: string | null; stock_code: string | null
  market: string | null          // Y=유가 K=코스닥
  action_type: string; report_nm: string | null
  rcept_dt: string               // YYYYMMDD
  market_cap: number | null; summary: string | null; dart_url: string
  is_correction: boolean         // [기재정정]·[첨부정정]
  my_group: MyGroup | null       // 내 묶음(stock_groups) 멤버
}
export interface ActionsResponse {
  items: CorporateAction[]; total: number
  as_of: string | null           // 마지막 DART 스캔 성공 시각(UTC)
  counts: { original: number; correction: number } | null
}
export interface RightsRow {
  rcp_no: string; stock_code: string | null; corp_name: string | null; action_type: string | null; method: string | null
  price_1st: number | null; price_2nd: number | null; price_final: number | null; latest_close: number | null
  diff_w: number | null; diff_pct: number | null; old_shares: number | null; new_shares: number | null; ratio_pct: number | null
  date_disclosure: string | null; date_price_1st: string | null; date_ex_rights: string | null; date_record: string | null
  date_rights_listing_start: string | null; date_price_fix: string | null; date_sub_start: string | null
  date_public_start: string | null; date_payment: string | null; date_rights_listing_end: string | null
  date_new_listing: string | null; underwriter: string | null; major_holder: string | null; dart_url: string
  my_group: MyGroup | null
}
export interface RightsResponse { items: RightsRow[]; as_of: string | null }

/* ---------- 인물 (spine_person) ---------- */
export interface PersonRow {
  entity_id: number; name: string; doc_count: number
  last_doc_at: string | null; last_doc_title: string | null; last_doc_id: number | null
  following: boolean; top_stocks: string[]
  mentions_7d: number; mentions_prev_7d: number; delta_7d: number   // 최근 7일 − 직전 7일
}
export interface PeopleDirectory { items: PersonRow[]; total: number; hidden_tail: number; as_of: string | null }
export interface FollowedPeopleWeek { items: PersonRow[]; as_of: string | null }
export type PeopleSort = 'surge' | 'total' | 'recent'
export interface PersonRelation {
  id: number; direction: 'out' | 'in'; rel_type: string
  other_id: number; other_name: string; other_type: string; other_aliases: string | null
  mechanism: string | null; epistemic_type: string; created_at: string | null
  narrative_topic: string | null; narrative_title: string | null; narrative_superseded: boolean
}
export interface PersonProfile { status: string; digest: string | null; insights: string | null; created_at: string | null }
export interface PersonDossier {
  entity_id: number; name: string; total_docs: number
  first_doc_at: string | null; last_doc_at: string | null; following: boolean
  profile: PersonProfile | null; profile_stale: boolean
  new_since_profile: number | null   // 프로필 생성 이후 수집된 언급 수
  co_entities: { entity_id: number; name: string; link_type: string; aliases: string | null; count: number }[]
  recent_docs: { id: number; title: string; published_at: string | null }[]
  relations: PersonRelation[]
}

/* ---------- 개인 투자 열기 (D-231) ---------- */
export type RetailRegimeKey = 'deleveraging' | 'leverage_led' | 'churn' | 'broad_inflow' | 'neutral'
export interface RetailRegime { key: RetailRegimeKey; label: string; reasons: string[] }
export interface RetailMetric {
  key: string; label: string; unit: 'rate' | 'ratio' | 'krw'
  value: number | null; pctile: number | null; pctile_change: number | null   // 과거 5년 백분위(그날 이전 값만)
}
export interface RetailSummary {
  as_of: string | null; regime: RetailRegime | null; metrics: RetailMetric[]
  levels: { credit_total?: number; deposits?: number; kospi_close?: number }
  krx_configured: boolean; accounts_available: boolean
}
export interface RetailSnapshot { episode: string; date: string; name: string; regime: RetailRegime; metrics: RetailMetric[]; levels: RetailSummary['levels'] }
export interface RetailPoint {
  date: string; credit_total: number | null; deposits: number | null; kospi_close: number | null; value: number | null
  credit_growth: number | null; credit_growth_pct: number | null; deposit_growth_pct: number | null; value_growth_pct: number | null
  leverage: number | null; turnover: number | null; indiv_share: number | null; forced_20_pct: number | null
}

/* ---------- 프록시 보드 (D-240, docs/specs/question-proxy.md §프록시 보드) ---------- */
export type ProxyDirection = 'up' | 'down'
export interface ProxyBoardSummary {
  id: number; name: string; description: string | null
  question_id: number | null; narrative_id: number | null; group_id: number | null
  created_at: string | null; updated_at: string | null
  item_count: number; in_warn_count: number
}
export interface ProxyLatest {
  value: number | null; as_of: string | null; change: number | null; change_pct: number | null
  change_basis: string | null; direction: 'up' | 'down' | 'flat' | null; unit: string | null
}
export interface ProxyBoardItem {
  proxy_id: number; position: number; label: string; adapter: string | null; adapter_ref: string | null
  unit: string | null; warn_direction: ProxyDirection | null; rationale: string | null; missing: boolean
  latest: ProxyLatest; in_warn: boolean; series: { date: string; value: number }[]
}
export interface ProxyBoardDetail extends ProxyBoardSummary { items: ProxyBoardItem[] }
export interface ProxyAdapter { kind: string; label: string; ref_format: string; description: string; change_basis: string }
export interface ProxyCatalogEntry { ref: string; label: string; unit: string | null }
export interface ProxyCandidate {
  label: string; adapter: string; adapter_ref: string; unit: string | null; warn_direction: ProxyDirection | null
  rationale: string | null; lead_or_confirm: 'lead' | 'confirm' | null; source_label: string
}
export interface ProxyNeedsSource { label: string; adapter: string | null; adapter_ref: string | null; rationale: string | null; reason: string }
export interface ProxySuggestion { topic: string; candidates: ProxyCandidate[]; needs_source: ProxyNeedsSource[] }

/* ---------- 월드모델 읽기 전용 (docs/specs/world-model.md) — 전부 저장분, LLM 없음 ---------- */
export interface WorldMega {
  id: number; name: string; title: string | null; narrative: string | null
  members: string[]; version: number; created_at: string | null
}
export interface WorldBigPicture {
  mega: WorldMega[]
  worldview: { briefing: string | null; created_at: string | null; stale: boolean } | null
  as_of: string | null
}
export interface WorldEdgeBrief { from: string; to: string; rel: string; effect_direction: string | null }
export interface WorldNarrativeChange {
  topic: string; narrative_id: number; version: number; title: string | null; category: string | null
  created_at: string | null; drift_summary: string | null; versions_in_window: number; is_first: boolean
  added_count: number; removed_count: number; added_edges: WorldEdgeBrief[]; removed_edges: WorldEdgeBrief[]
}
export interface WorldNarrativeChanges { days: number; items: WorldNarrativeChange[]; as_of: string | null }
export interface WorldContestedItem {
  id: number; statement: string; pace_layer: string; contested_at: string | null; refute: number; support: number
  latest_refute: { doc_id: number | null; title: string | null; observed_at: string | null } | null
}
export interface WorldContested { items: WorldContestedItem[]; as_of: string | null }
export interface WorldStockNarratives {
  stock_code: string; name: string | null; kinds: StockGroupKind[]
  narratives: { topic: string; narrative_id: number; title: string | null; version: number; created_at: string | null
    drift_summary: string | null; edges: number; via: 'edge' | 'neighbor' }[]
  latest_drift: string | null; latest_at: string | null
}
export interface WorldMyStocks { stocks: WorldStockNarratives[]; members: number; covered: number; as_of: string | null }
export interface WorldCheckpoint {
  status: 'ok' | 'empty'; topic: string; narrative_id?: number | null; title?: string | null
  core_question?: string | null
  question?: { id: number; text: string; status: string; lead_verdict: string | null; confirm_verdict: string | null } | null
  falsifiers?: { condition: string; source: 'knowledge' | 'question'; about: string | null }[]
  beneficiaries?: { name: string; type: string; via: 'chain' | 'claim'; stock_code: string | null }[]
  my_stocks?: { stock_code: string; name: string | null; kinds: StockGroupKind[]; edges: number }[]
}

/** 가파른 추세 종목 — GET /api/spine/trend-leaders (탐색 위젯) */
/** 조건별 실제 값 + 최근 120거래일 차트 재료 */
export interface TrendEvidence {
  close: number; ma20: number; ma60: number; ma60_prev: number; plus_di: number; minus_di: number
  fit_start: number; fit_end: number; dates: string[]; closes: number[]; ma20_series: (number | null)[]; ma60_series: (number | null)[]
}
/** high52 = 52주 신고가 돌파 · vp_retest = 매물대 돌파 후 지지 */
export type TrendEventKind = "high52" | "vp_retest"
export interface TrendEvent {
  stock_code: string; name: string; sector: string | null; close: number
  kind: TrendEventKind; date: string; level: number; held: boolean; detail: string
}
export interface TrendLeader {
  stock_code: string; name: string; sector: string | null; market_cap: number | null; close: number
  ret_20: number; ret_60: number; r2: number; adx: number; gap_ma20: number; score: number; new: boolean
  events: TrendEventKind[]; evidence: TrendEvidence; spark: number[]
}
export interface TrendLeadersResponse {
  as_of: string | null; computed_from: string | null; criteria: string; universe: number; passed: number
  items: TrendLeader[]; events: TrendEvent[]
}

/** GET /api/spine/transcript/follow 중 위젯이 읽는 필드 (전체 행은 follow/TranscriptPage) */
export interface TranscriptFollowSummary {
  ticker: string; company_name: string; next_report_date?: string | null; calendar_checked_at?: string | null
  latest: { transcript_id: number } | null
}
