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

export interface BusinessSegment {
  id: number;
  corp_code: string;
  bsns_year: number;
  segment_type: string;
  segment_name: string;
  revenue: number | null;
  ratio: number | null;
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
  /** 검색어가 있을 때만 — 검색 결과 전체의 소스별 건수와 자주 같이 나온 종목·산업·주제 (ia-redesign §4.15) */
  facets?: SpineFeedFacets | null;
}
export interface SpineFeedFacets {
  sources: Record<string, number>;
  entities: { name: string; link_type: string; aliases: string | null; count: number }[];
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
  sector: string | null;       // 실적 시즌 섹터 이름 (팔로우 밖이면 null)
  sector_etf: string | null;   // 실적 반응 비교 ETF
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

/** AI 대화 › 대상 붙이기 (ia-redesign §4.14a, D-311) — 서버 models/chat_targets.py와 같은 모양 */
export type ChatTargetKind = 'stock' | 'us_stock' | 'narrative' | 'question' | 'doc' | 'person' | 'theme' | 'peer_group' | 'report';
/** 요청 본문·보낸 질문의 칩 — 이름 대신 식별자 */
export interface AttachmentRef {
  kind: ChatTargetKind;
  ref: string;
  label: string;
}
/** 후보·붙어 있는 대상 — 칩 표시 정보 포함 */
export interface ChatTarget extends AttachmentRef {
  sub?: string | null;
  date?: string | null;
  code?: string | null;
  change_pct?: number | null;
  /** false = 사라짐(보관된 서사·지운 자료) — 흐린 칩, 보낼 때 뺀다 */
  available?: boolean;
}
export interface ChatTargetSearch {
  query: string;
  kind: ChatTargetKind | null;
  groups: { kind: ChatTargetKind; items: ChatTarget[] }[];
}

export interface ConversationDetail {
  study?: {id:number; title:string} | null;
  study_project?: {id:number; title:string} | null;
  id: number;
  title: string | null;
  channel: string;
  attached_documents?: { id: number; title: string | null }[]
  /** 대화에 붙어 있는 대상 — 다음 질문에도 칩으로 남는다 */
  attached_refs?: ChatTarget[]
  messages: {
    id: number;
    role: string;
    content: string;
    citations: { n: number; doc_id: number | null; title: string; href?: string | null; kind?: string; published_at?: string | null }[] | null;  // published_at: 수집 자료 게시일(상세 조회 때 붙임)
    gaps: { type: string; note: string }[] | null;
    model: string | null;
    route?: ChatRoute | null;
    /** user: 보낼 때 붙어 있던 대상 */
    attachments?: AttachmentRef[] | null;
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

/** 산업 맵 RS 궤적 — 1·2·3주 전 위치 (sector_rs) */
export interface SectorTrailPoint { weeks_ago: number; rs_long: number | null; rs_short: number | null }

/** GET /api/spine/sector-map/peers — 섹터 → Peer 그룹 대응(서버 sector_peer_map, D-301 6). share = 그룹 구성 종목 중 이 섹터 비율 */
export interface SectorPeerLink {
  group_id: string; group_name: string; scope: 'product' | 'value_chain'
  source: 'seed' | 'auto'; partial: boolean
  members: number; classified: number; in_sector: number; share: number | null
}
export interface SectorPeerEntry { sector: string; partial: boolean; note: string | null; links: SectorPeerLink[] }
export interface SectorPeers { catalog_as_of: string; auto_share: number; sectors: SectorPeerEntry[] }

/** 섹터 대표지수 (D-327-4) — etf = 대표 ETF 종가, computed = Explorer 계산 지수(시총 가중) */
export interface SectorBenchmark { kind: 'etf' | 'computed'; ticker: string | null; name: string | null; tracks: string | null; note: string | null }
interface SectorQuote { last: number | null; last_date: string | null; chg_1d: number | null; ret_1m: number | null; ret_3m: number | null }
interface SectorRs { rs_long: number | null; rs_short: number | null; chg_5d: number; trail: SectorTrailPoint[]; market_cap: number; stocks: number }
/** GET /api/spine/industry/map — 섹터 지도 (backend/models/industry.py) */
export interface IndustryMapSector extends SectorQuote, SectorRs {
  name: string; benchmark: SectorBenchmark; peer_groups: number | null; series: number[]
}
export interface IndustryMap {
  as_of: string | null; kospi: number[]; sectors: IndustryMapSector[]
  outside_groups: { id: string; name: string; members: number }[]; peers_available: boolean
}
export interface SectorConstituent {
  stock_code: string; corp_name: string; market_cap: number | null; weight: number
  chg_1d: number | null; ret_1m: number | null; rs_long: number | null; rs_short: number | null
}
export interface SectorNarrative { id: number; topic: string; title: string; core_question: string | null; docs: number | null; updated_at: string | null }
export interface SectorDoc { id: number; type: 'blog' | 'scrap' | 'web' | 'youtube'; title: string; published_at: string | null }
export type SectorDataKind = 'trade' | 'taiwan' | 'valuechain' | 'usSeason' | 'credit'
export interface SectorDataLinkCard {
  kind: SectorDataKind; label: string; title: string; value: number | null; value_kind: 'usd' | 'pct' | null
  change: number | null; sub: string; count: number; href: string; filtered: boolean; verdict: string | null
}
/** GET /api/spine/industry/{sector} — 섹터 화면 머리·개요·종목 */
export interface IndustrySectorDetail extends SectorQuote, SectorRs {
  as_of: string | null; name: string; benchmark: SectorBenchmark
  series: { d: string; v: number; k: number | null }[]
  top_weights: SectorConstituent[]; constituents: SectorConstituent[]
  narratives: SectorNarrative[]
  overview: { question: string; bullets: string[]; model: string | null; generated_at: string; narrative_ids: number[] } | null
  docs: SectorDoc[]
  peer_groups: number | null
  data_links: SectorDataLinkCard[]
  feed_industry: string | null; entity_id: number | null
}
/** GET /api/spine/industry/{sector}/peers — 하위 Peer 그룹 */
export interface SectorPeerGroupRow {
  id: string; name: string; scope: 'product' | 'value_chain'; parent: string | null; partial: boolean; auto: boolean
  members: number; med_20d: number | null; med_60d: number | null
}
export interface SectorPeerList { sector: string; catalog_as_of: string; prices_as_of: string; groups: SectorPeerGroupRow[] }

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
  platform: 'telegram' | 'blog' | 'youtube' | 'memo' | 'system'
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
/** 피드 '모두 읽음'(POST /api/spine/feed/channels/read-all, D-301) — all = 사람 소스 전체(Explorer 산출물 제외) */
export type MarkAllReadPlatform = 'all' | 'telegram' | 'blog' | 'youtube' | 'memo'
export interface MarkAllReadResponse { platform: string; read_until: string; channels: number; marked: number }
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
  market?: 'kr' | 'us';
}
export interface StockGroupMember {
  id: number; group_id: number; stock_code: string; name: string; market: string | null;
  bought_at: string | null;
  conviction: number | null; target_price: number | null; thesis: string | null; created_at: string;
  /** 추적(알림 대상) 표시 0|1 — 관심 묶음만 (D-293) */
  tracked: number;
  close: number | null; change_pct: number | null; market_cap: number | null; price_date: string | null;
  rule_count: number; signals: { rule_id: number; strategy_id: string; label: string; value: number | null; reference: number | null; signal_date: string | null }[];
  unavailable: number;
}
/** PUT /api/spine/groups/:id/members/:code/tracked — tracked_codes = 지금 알림 대상 전체(국내·미국) */
export interface StockGroupTrackedState { group_id: number; stock_code: string; tracked: boolean; tracked_codes: string[] }
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
/** 국내 시장 폭(D-321) — GET /api/spine/indices/breadth. 자료가 없으면 응답이 null */
export interface KrBreadth {
  trade_date: string
  prev_date: string
  up: number
  down: number
  flat: number
  up_ratio: number
}

/** 홈 › 한국·미국 시장 ① 지수 차트 + 요약 지표 (ia-redesign §4.2·4.3, D-325) — GET /api/spine/market/{kr|us}/overview */
export type MarketKey = "kr" | "us"
export type IndexRangeKey = "1d" | "1m" | "3m" | "1y"
export interface IndexRange {
  key: IndexRangeKey
  /** 기준선 — 1일은 전일 종가, 기간은 기간 시작 전 값 */
  base: number | null
  /** 1일 = 현지 'HH:MM', 기간 = 'YYYY-MM-DD' */
  points: { t: string; v: number }[]
}
export interface IndexSession {
  /** pre = 개장 전(1일은 직전 거래일 경로) · open = 장중 · closed = 마감·휴장 */
  state: "pre" | "open" | "closed"
  trade_date: string | null
  last_time: string | null
  last_kst: string | null
  open: string
  close: string
}
export interface IndexOverview {
  key: string
  name: string
  value: number | null
  change: number | null
  change_pct: number | null
  prev_close: number | null
  session: IndexSession
  ranges: IndexRange[]
}
export interface OverviewTile {
  key: "breadth" | "indiv_net" | "usdkrw" | "credit" | "fear_greed" | "us10y" | "dxy" | "wti"
  label: string
  value: number | null
  change_pct: number | null
  as_of: string | null
  series: number[]
  up?: number | null
  down?: number | null
  flat?: number | null
  buy?: number | null
  sell?: number | null
  growth_20?: number | null
  pctile?: number | null
  second?: number | null
}
export interface MarketOverview {
  market: MarketKey
  indices: IndexOverview[]
  tiles: OverviewTile[]
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
export interface CallGuidance { metric: string; direction: 'raised' | 'lowered' | 'maintained' | 'initiated' | 'unknown'; quote: string; source: string }   // unknown = 추출 모델이 방향을 못 정함(PANW 2026-10)
export interface CallMomentumCandidate {
  ticker: string; name: string | null; event_date: string; score: number; first_candidate_at: string | null
  summary?: string | null                      // AI 핵심 요약(이번 시즌 후보만, 근거 기반 sonnet) — 없으면 근거만
  drivers: CallDriver[]; guidance: CallGuidance[]; tone: number | null; prev_tone: number | null; sources: string[]; qa_focus: string[]
  /** 기대 초과 가속(2026-11-04): 숫자(매출 성장률이 직전 분기보다 빨라짐 + 컨센서스 상회·가이던스 상향) 우선, 없으면 원문 근거 */
  accel?: CallAccel | null
}
export type CallAccel =
  | { on: boolean; basis: 'numeric'; quarter: string; g_now: number; g_prev: number; gap: number; beat: number | null; guidance_raised: boolean }
  | { on: boolean; basis: 'quote'; quote?: string | null; vs?: string | null }
  | { on: boolean; basis: 'none' | 'first' }
export interface CallMomentumSeason { key: string; label: string; start: string }
export interface CallMomentum {
  season: CallMomentumSeason & { reported: number }
  candidates: CallMomentumCandidate[]          // 이번 실적 시즌만 — 새 모멘텀
  continuing?: CallMomentumCandidate[]         // 이번 실적 시즌 이어지는 모멘텀(최근 두 발표에도 모멘텀)
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

/** POST /api/spine/transcript/check/{ticker} — 이 종목의 가장 최근 실적 발표 조사(SEC 8-K·yfinance·Fool) */
export interface TranscriptCheck {
  ticker: string
  latest_release: { date: string; fiscal_year: number; fiscal_period: string; cy: string | null } | null   // SEC 8-K 실적 발표
  calendar: { last_report_date: string | null; next_report_date: string | null } | null                    // yfinance
  transcript_id: number | null          // 그 분기 녹취록이 저장돼 있으면
  fool: { available: boolean | null; url?: string | null; error?: string } | null   // 미저장일 때만 확인
  sec_error: string | null
}

/** GET·POST /api/spine/transcript/detail/{id}/reaction — 컨콜 시장 반응(발표일~7일) */
export interface CallReactionSource {
  n: number; kind: "doc" | "headline"; title: string | null; source: string | null; published_at: string | null; cited: boolean
  doc_id?: number; source_type?: string; url?: string
}
export interface CallReaction {
  transcript_id: number
  window_start: string; window_end: string
  status: "interim" | "final"          // interim = 기간 진행 중 중간 정리
  body: string | null                  // null = 기간 안에 자료 없음
  prices: { base_date: string; base_close: number; days: { date: string; close: number; ret: number | null; spy_ret: number | null }[] } | null
  sources: CallReactionSource[]
  n_docs: number                       // 기간 안에서 찾은 내 자료 수(정리엔 상위 40)
  created_at: string
  meta?: ReactionMeta | null           // 구조화 필드(실적 시즌 체인, D-277)
}

/* ---------- 실적 시즌 체인 (docs/specs/earnings-season.md) ---------- */
export type CoreReason = "cap" | "mention" | "holding_chain" | "dc_chain" | "pinned"
export type EvalVerdict = "hit" | "underweighted" | "noise" | "missed" | "minor"

export interface ReactionGrade { issue: string; weight: "high" | "mid" | "low" | null; drove: "major" | "minor" | "none" | null; outcome: string | null; verdict: EvalVerdict | null }
export interface ReactionMeta {
  headline?: string; interpretation?: "positive" | "neutral" | "negative"
  welcomed?: string[]; questioned?: string[]
  surprise?: { revenue?: string; eps?: string; guidance?: string; one_off?: string | null }
  call_points?: string[]; react_points?: string[]
  issue_verdicts?: { issue: string; drove: string; outcome?: string }[]
  missed?: string[]; vs_prev?: string[]
  d1?: number | null; d7?: number | null       // 업종 ETF 대비 초과수익 %p
  grades?: ReactionGrade[]; expectation_prompt?: string | null
}

export interface ExpectationIssue { issue: string; why?: string; good?: string; bad?: string; weight?: "high" | "mid" | "low"; cites?: number[] }
export interface Expectation {
  ticker: string; fiscal_year: number; fiscal_period: string; snapshot: "d7" | "d1"; event_date: string | null
  quant: { etf?: string; eps_est?: number | null; rev_est?: number | null; eps_rev_up30?: number; eps_rev_down30?: number
    runup30?: number | null; runup30_vs_spy?: number | null; runup30_vs_etf?: number | null
    pt30?: { n: number; up: number; down: number; median_pct: number | null; examples: string[] }; implied_move?: number | null } | null
  issues: ExpectationIssue[] | null; points: string[] | null; positioning: string | null; thin: string | null
  n_docs: number | null; prompt_version: string | null; created_at: string
}

export interface SeasonItem {
  ticker: string; name: string | null; sector: string; sector_name: string; event_date: string; fiscal: string
  transcript_id: number | null; reaction: "interim" | "final" | null; core: CoreReason[]
  eps_surprise: number | null; headline: string | null; interpretation: string | null
  confirmed: boolean   // false = 회사가 아직 확정하지 않은 예정일(yfinance 추정)
  d1?: number | null; d7?: number | null; d30?: number | null; latest?: number | null; latest_date?: string | null
  follow?: "유지" | "확대" | "되돌림" | "반전" | null
  expectation?: { d7: boolean; d1: boolean; qualitative: boolean }   // 곧 발표만
}
export interface SeasonSectorRow {
  key: string; name: string; etf: string; verdict: string | null; one_line: string | null
  n_reported: number; n_reactions: number; tickers: { ticker: string; d1: number | null }[]; dc_chain: boolean
}
export interface SeasonWindow { key: string; label: string; first: string; last: string; events: number; confirmed: number }
/** 발표 캘린더 하루 — 팔로우 기업 발표 수, 그중 핵심·확정 수, 종목(ia-redesign §4.6a) */
export interface SeasonCalendarDay { date: string; total: number; core: number; confirmed: number; tickers: string[] }
export interface SeasonOverview {
  season: { key: string; label: string; start: string; is_current: boolean }
  counts: { followed: number; reported: number; beat: number; beat_down: number; reversed: number; reactions: number; reactions_final: number
    up: number; miss: number; miss_up: number }   // up = 첫 거래일 업종 ETF보다 강했다, miss_up = EPS 하회인데 강했다
  changes: { reactions: string[]; themes: string[]; expectations: string[]; transcripts: string[] }
  last_run: string | null
  /** 시즌별 발표 구간(팔로우 기업 첫~마지막 발표일, 미확정 포함) — 홈 미국 시장 '시즌 사이' 판정 (ia-redesign §4.28) */
  windows: SeasonWindow[]
  calendar: SeasonCalendarDay[]
  sectors: SeasonSectorRow[]; top_up: SeasonItem[]; miss_up: SeasonItem[]; beat_down: SeasonItem[]; reversed: SeasonItem[]; upcoming: SeasonItem[]
  evals: { hit: number; underweighted: number; noise: number; missed: number; cases: { ticker: string; issue: string; verdict: EvalVerdict }[] }
  core: { criteria: Record<CoreReason, string>; tickers: { ticker: string; name: string | null; reasons: CoreReason[] }[] }
  reported: SeasonItem[]
}
/** 국내 실적 시즌(ia-redesign §4.22) — GET /api/spine/transcript/season/kr. 백엔드 models/kr_season.py와 같은 모양 */
export type KrReactionState = "final" | "same_day"
export interface KrAnnouncement {
  corp_code: string; corp_name: string; stock_code: string | null
  /** 잠정실적(또는 분기보고서) 공시 접수일(발표 시각은 모른다) */
  rcept_dt: string; rcp_no: string
  /** prelim = 잠정실적, quarterly = 잠정실적 없이 분기보고서만 낸 회사(D-305, 반응 집계에는 포함) */
  kind: "prelim" | "quarterly"
  /** 분기보고서만 낸 회사는 null */
  basis: "연결" | "별도" | null; group: string | null; market_cap: number | null
  /** 첫 반응 = 공시 전 종가 → 다음 거래일 종가(%), x = 같은 업종 중앙값 대비 %p(표본 5 미만이면 null) */
  r1: number | null; x1: number | null; r1_state: KrReactionState | null
  r5: number | null; x5: number | null; r5_state: "final" | "pending" | null
  /** 2단계(공시 본문 파싱) 전까지 null */
  figures: { revenue_yoy: number | null; op_income_yoy: number | null } | null
}
export interface KrSeasonGroup { group: string; n: number; quarterly_n: number; median_r1: number | null; median_x1: number | null; up_n: number; base_n: number; up_ratio: number | null }
export interface KrSeasonPending { corp_code: string; corp_name: string; stock_code: string; group: string | null; market_cap: number | null; prev_date: string }
export interface KrSeasonOverview {
  season: { key: string; label: string; start: string; is_current: boolean }
  seasons: { key: string; label: string; count: number; is_current: boolean; partial: boolean }[]
  deadline: string; today: string; prices_as_of: string | null; disclosures_as_of: string | null
  coverage: { partial: boolean; full_from: string | null }
  kpi: {
    /** reported = 잠정실적 기준, quarterly_only = 분기보고서만 낸 곳(따로 셈) */
    reported: number; quarterly_only: number; prev_reported: number
    week: { n: number; start: string; end: string; first: string | null; last: string | null } | null
    outperform_n: number; outperform_base: number; outperform_ratio: number | null; median_x1: number | null
  }
  changes: { added_date: string | null; added: string[]; settled_date: string | null; settled: string[] }
  /** total = 잠정실적 공시 수, quarterly = 분기보고서만 낸 회사 수 */
  calendar: { date: string; total: number; quarterly: number }[]
  announcements: KrAnnouncement[]
  groups: KrSeasonGroup[]
  pending: KrSeasonPending[]
}
export interface SectorTheme {
  id: number; verdict: string | null; tickers: string; created_at: string
  body: { one_line?: string; welcomed?: string[]; questioned?: string[]; change_note?: string | null; next?: string[]; vs_last_season?: string[] }
}
export interface SectorDetail {
  key: string; name: string; etf: string; season: string; seasons: string[]
  members: { ticker: string; name: string | null }[]
  theme: SectorTheme | null; theme_history: SectorTheme[]
  companies: (Partial<SeasonItem> & { ticker: string; name: string | null; status: "reported" | "upcoming" | "none"; core: CoreReason[] })[]
  /** 시즌 한 달 같은 달력 축 — 업종 ETF 대비 누적 %p(창 첫 거래일 = 0), events = 티커 → 발표일 */
  timeline: { start: string | null; end: string | null; view_end: string | null; series: Record<string, [string, number][]>; events: Record<string, string> }
  history: { season: string; label: string; rows: { ticker: string; d1: number | null }[]; verdict: string | null; one_line: string | null }[]
}
export interface ChainDetail {
  ticker: string; name: string | null; sector: string; sector_name: string; etf: string; event_date: string | null
  expectation: Expectation | null; reaction_meta: ReactionMeta | null; reaction_status: "interim" | "final" | null
  series: { date: string; offset: number; ret: number; bench: number; excess: number; volume: number | null }[]   // 발표 전 마지막 거래일 = 0
  mentions: { day: string; n: number }[]          // 'MM-DD' 한국 시각
  pt_after: { n: number; up: number; down: number; median_pct: number | null; examples: string[] } | null
  history: { fiscal: string; event_date: string; season: string; transcript_id: number | null; d1: number | null; d7: number | null; d30: number | null
    follow: string | null; pt_up: number | null; pt_down: number | null; headline: string | null; reaction: string | null }[]
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
  yoy: number | null; mom: number | null; z: number | null; flag: Exclude<TradeFlag, 'none'>; reason: string | null
  contribution: number | null; nested_in: string | null
  yoy3m: number | null   // 3개월 합의 전년 동기 대비(비율)
}
export interface TradeHighlights {
  period: string | null; periods: string[]; total_usd: number
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
  description: string | null     // 제목 아래 한 줄 — 증자 상세·저장 요약 첫 문장(서버 결정적, D-306)
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
export type PeopleSort = 'surge' | 'total' | 'recent'
export interface PersonRelation {
  id: number; direction: 'out' | 'in'; rel_type: string
  other_id: number; other_name: string; other_type: string; other_aliases: string | null
  mechanism: string | null; epistemic_type: string; created_at: string | null
  narrative_topic: string | null; narrative_title: string | null; narrative_superseded: boolean
}
export interface PersonProfile { status: string; digest: string | null; insights: string | null; created_at: string | null }

/* ---------- 인물 1단계 (ia-redesign §4.23) — 인물 홈 · id 기반 상세 ---------- */
export type PersonRoleName = 'policy' | 'executive' | 'guru'
export type PremiseStatus = 'supports' | 'challenges' | 'mixed' | 'untestable' | 'nodata'
export interface PersonRole { role: PersonRoleName; org: string | null; org_code: string | null; title: string | null; source: string }
/** 전제 '누가' 한 칸 — 인물이면 대표 인물 id(엔티티가 없으면 null), 기관이면 텍스트만 */
export interface WhoPerson { label: string; kind: 'person' | 'org'; entity_id: number | null; name: string | null }
export interface PremiseVerdict { key: string; claim: string; status: PremiseStatus | null }
export interface PeopleHomeRow {
  entity_id: number; name: string; role: PersonRole | null; doc_count: number
  mentions_7d: number; delta_7d: number
  last_doc_title: string | null; last_doc_id: number | null; last_doc_at: string | null
  top_stocks: string[]; following: boolean; records: number
}
export interface RecordedPerson { entity_id: number | null; name: string; role: PersonRole | null; doc_count: number; premises: PremiseVerdict[] }
export interface PeopleHome {
  summary: { followed: number; followed_mentions_7d: number; recorded_people: number; premises: number; mentioned: number; mentioned_2plus: number }
  role_counts: Record<string, number>
  followed: PeopleHomeRow[]
  recorded: RecordedPerson[]
  recorded_status: 'ok' | 'error'
  rising: PeopleHomeRow[]
  as_of: string | null
}
export interface PersonResolve { entity_id: number | null; name: string | null }
export interface MergedName { entity_id: number; name: string; type: string; docs: number; rule: string | null }
export interface PersonDocRow { id: number; title: string; published_at: string | null; source_type: string | null }
export interface PersonPremise {
  key: string; claim: string; status: PremiseStatus | null; kind: string
  evidence: string[]; rule: string; sources: EraSource[]; said_at: string | null; co_holders: WhoPerson[]
}
export interface PersonDetail {
  entity_id: number; requested_id: number; name: string; role: PersonRole | null
  merged_names: MergedName[]; following: boolean
  mentions: { count: number; first_at: string | null; last_at: string | null }
  own_docs: PersonDocRow[]; own_total: number; own_source: string | null
  cited: PersonDocRow[]; cited_total: number
  flow: { year: string; own: number; cited: number }[]
  premises: PersonPremise[]; premises_status: 'ok' | 'error'
  co_entities: { entity_id: number; name: string; link_type: string; aliases: string | null; count: number }[]
  relations: PersonRelation[]
  profile: PersonProfile | null; profile_stale: boolean; new_since_profile: number | null
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
  /** 이번 주 Market Today 연결 화두·회차(멤버 서사끼리 중복 제거, 마감 정리 제외)와 '다음 갱신 앞당김' (ia-redesign §9·§4.25) */
  mt_topics: number; mt_sessions: number; boost: boolean
}
/** 큰 그림 줄기 상태 — 강해짐 · 엇갈림 · 약해짐 · 새로 (ia-redesign §4.25) */
export type StrandStatus = 'strengthening' | 'mixed' | 'weakening' | 'new'
export interface WorldNarrativeChip { narrative_id: number; topic: string; version: number; created_at: string | null; is_new: boolean }
export interface WorldStrandEvidence {
  kind: 'market_today' | 'overnight'
  ref: string            // mt:<id>:<순번> | ov:<거래일>:<순번> — 서버는 id만 저장, 문장은 읽을 때 원천에서
  label: string          // 'Market Today 11/4 15:40' · 'Overnight 11/3'
  text: string
  date: string
}
export interface WorldStrand {
  title: string; status: StrandStatus; narratives: WorldNarrativeChip[]
  mt_topics: number; mt_sessions: number; boost: boolean
  evidence: WorldStrandEvidence[]
}
export interface WorldPremise { text: string; shaken_by: (WorldNarrativeChip & { quote: string }) | null }
export interface WorldRebuildState {
  available: boolean
  reason: 'cooldown' | 'budget' | 'unavailable' | null
  retry_at: string | null    // UTC(DB 표기)
  budget_left: number
}
export interface WorldBigPicture {
  /** generated = 주간 생성분(줄기·전제) · mega = 첫 생성 전(메가 서사 + 세계관 브리핑 전제) */
  source: 'generated' | 'mega'
  strands: WorldStrand[]
  premises: { settled: WorldPremise[]; contested: WorldPremise[] }
  generated_at: string | null
  week: string | null
  mega: WorldMega[]
  worldview: { briefing: string | null; created_at: string | null; stale: boolean } | null
  as_of: string | null
  /** 근거 범위 (ia-redesign §4.25 머리) */
  inputs: { narratives: number; mt_sessions: number; overnight_days: number }
  inputs_as_of: string | null              // 근거 중 가장 늦은 시각(UTC, DB 표기)
  stale_days: number | null                // 기준 시각 경과일(생성분) · 세계관 브리핑 경과일(첫 생성 전)
  new_versions_since: number | null        // 생성(또는 브리핑) 뒤 새 내러티브 버전 수
  rebuild: WorldRebuildState
}
export interface WorldRebuildResult {
  status: 'ok' | 'skipped' | 'cooldown' | 'budget' | 'unavailable' | 'failed' | 'empty' | 'off'
  reason?: string | null; retry_at?: string | null; key?: string | null; strands?: number | null
}
export interface WorldEdgeBrief { from: string; to: string; rel: string; effect_direction: string | null }
export interface WorldNarrativeChange {
  topic: string; narrative_id: number; version: number; title: string | null; category: string | null
  created_at: string | null; drift_summary: string | null; versions_in_window: number; is_first: boolean
  change_summary: string | null   // 서사가 어떻게 옮겨 갔나 1~2문장 (홈 위젯)
  added_count: number; removed_count: number; added_edges: WorldEdgeBrief[]; removed_edges: WorldEdgeBrief[]
}
export interface WorldNarrativeChanges { days: number; items: WorldNarrativeChange[]; as_of: string | null }
export interface WorldContestedItem {
  id: number; statement: string; pace_layer: string; contested_at: string | null; refute: number; support: number
  latest_refute: { doc_id: number | null; title: string | null; observed_at: string | null } | null
}
export interface WorldContested { items: WorldContestedItem[]; as_of: string | null }
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
  fit_start: number; fit_end: number
}
/** 52주 신고가 단계 — breakout(최근 5거래일 전고점 돌파) · retest(60거래일 안 돌파 → 돌파선 근처 지지 → 재반등) */
export interface TrendHigh52 {
  kind: "breakout" | "retest"; date: string; level: number; touch_date?: string | null; touch_low?: number | null; detail: string
}
/** GET /api/spine/trend-leaders/{code}/chart — 근거 창 차트 ≈ 2년(종가·MA20·MA60·52주 고점선) */
export interface TrendChart {
  stock_code: string; dates: string[]; closes: number[]; ma20: (number | null)[]; ma60: (number | null)[]; high52: (number | null)[]
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
  events: TrendEventKind[]; high52?: TrendHigh52 | null; evidence: TrendEvidence; spark: number[]
}
export interface TrendLeadersResponse {
  as_of: string | null; computed_from: string | null; criteria: string; universe: number; passed: number
  items: TrendLeader[]; events: TrendEvent[]
}

/** 대만 월매출 — GET /api/spine/tw/revenue (금액 단위 천 TWD) */
export interface TwRevenuePoint { ym: string; revenue: number | null; yoy_pct: number | null }
export interface TwRevenueItem {
  code: string; name: string; layer: string; role: string; market: string | null
  ym: string | null; revenue: number | null; yoy_pct: number | null; mom_pct: number | null; yoy_3m: number | null
  lagging: boolean; note: string | null; series: TwRevenuePoint[]
}
export interface TwRevenueResponse {
  as_of: string | null; fetched_at: string | null; reported: number; total: number
  layers: { key: string; label: string }[]; items: TwRevenueItem[]
}

/** 대만 → 한국 연결 — GET /api/spine/tw/links (docs/specs/tw-revenue.md §6) */
export type TwLinkRelation = "peer" | "demand" | "capex"
export interface TwLink {
  kr_code: string; kr_name: string; relation: TwLinkRelation; confidence: "상" | "중" | "중하"; reason: string
  tw: { code: string; name: string }[]
  ym: string | null; yoy: number | null; yoy_3m: number | null; yoy_3m_prev: number | null
  state: "가속" | "둔화" | "전환↑" | "전환↓" | "유지" | null
  series: { ym: string; yoy: number }[]
  evidence: { best_lag: number | null; n: number; corr: number | null; same_dir: number | null }
}
export interface TwLinksResponse { as_of: string | null; items: TwLink[] }

/** 한국 확인 신호 — GET /api/spine/tw/confirm (docs/specs/value-chain.md §4) */
export type KrDirection = "up" | "down" | "flat" | null
export interface KrTradeSignal {
  hs: string; period: string | null; yoy_3m: number | null; yoy_3m_prev: number | null; state: TwLink["state"]
  relation: "direct" | "demand"; note: string; confidence: "상" | "중" | "하"
}
export interface KrConfirm {
  stock_code: string; taiwan: TwLink | null; trade: KrTradeSignal[]; trade_counted: string | null
  disclosure: {
    contracts_90d: number; contracts_prev_90d: number; capex_180d: number; last_contract: string | null
    last_prelim: { date: string; title: string; url: string | null } | null; direction: "up" | "down" | "flat"
  }
  directions: { taiwan: KrDirection; trade: KrDirection; disclosure: KrDirection }
  agree_up: number; observed: number
}

/** 밸류체인 지도 — GET /api/spine/tw/value-chain (docs/specs/value-chain.md) */
export interface VcNode {
  key: string; name: string; description: string
  tw: { code: string; name: string }[]; kr: { code: string; name: string }[]
  yoy_3m: number | null; yoy_3m_prev: number | null; state: TwLink["state"]; series: { ym: string; yoy: number }[]
  freq?: "M" | "Q"; obs_label?: string | null; period?: string | null
  state_z?: number | null; obs_kind?: "direct" | "proxy" | null; obs_caveat?: string | null
  source?: "tw" | "us" | "kr_trade" | "ext" | null; us_members?: UsMember[]; aux?: VcAux[]; market?: VcMarket[]; pxq?: VcPxq[]
}
/** 한국 수출 P×Q 분해 — 금액 = 단가·구성(금액/kg) × 물량(kg), 3개월 YoY */
export interface VcPxq { hs: string; item: string; period: string; value_yoy: number; qty_yoy: number; price_yoy: number; price_share: number | null; verdict: string }
/** 신용·금리 여건 — 수준과 약 3개월 변화(change_days가 실제 비교 기간), 긴축·완화·유지 */
export interface VcMarket { ref: string; label: string; missing: boolean; as_of?: string | null; value?: number | null; unit?: string | null; change_3m?: number | null; change_days?: number | null; state?: string | null }
/** 교차 확인 지표 — 월간 외부 시계열(WSTS·Census·SEAJ·대만 수출수주), missing=아직 수집 전 */
export interface VcAux { series: string; label: string; missing: boolean; note?: string | null; period?: string | null; yoy_3m?: number | null; yoy_3m_prev?: number | null; state?: string | null }
/** 미국 수요 기업 최신 분기 값 — 수요 칸·AI 가속기 상세 */
/** 10% 이상 고객 비중(SEC 10-K/10-Q 주석) — label null은 익명 고객(글자가 공시마다 같은 회사라는 보장 없음) */
export interface CustomerConcentration {
  period_end: string; period_kind: "Q" | "FY"; customers: { label: string | null; pct: number }[]
  top_trend: { period_end: string; top_pct: number }[]
}
export interface UsMember {
  ticker: string; name: string; metric: string; q: string; value: number; yoy: number | null; qoq_delta?: number | null
  customers?: CustomerConcentration | null
}
/** 최종 수요 — AI·스마트폰은 미국 분기 실적으로 관측(obs_label), PC는 대리 관측만 */
export interface VcDemand {
  key: string; name: string; description: string; obs_label?: string | null; us_members?: UsMember[]; aux?: VcAux[]
  yoy_3m?: number | null; yoy_3m_prev?: number | null; state?: TwLink["state"]; period?: string | null; series?: { ym: string; yoy: number }[]
  freq?: "M" | "Q"; state_z?: number | null
}
export interface VcEdge {
  from: string; to: string; kind: "supply" | "capex"; reason: string
  verdict: "확인" | "부분" | "미확인" | "관측 불가"; lag?: number | null; lag_consistent?: boolean | null
  signals: Record<string, { best_lag: number | null; corr: number | null; n: number; passed: boolean }>
}
export interface ValueChainResponse {
  as_of: string | null; demands: VcDemand[]
  tiers: { key: string; label: string }[]; lanes: { key: string; label: string }[]
  layout: Record<string, { tier: string; lane: string }>
  nodes: VcNode[]; edges: VcEdge[]; thresholds: Record<string, number>
}
export interface PropRow { stock_code: string; name: string; directions: KrConfirm["directions"]; agree_up: number; observed: number }
export interface PropLead {
  leader: string; leader_name: string; leader_state: string; follower: string; follower_name: string
  follower_state: string | null; months: number; verdict: string; status: "반영됨" | "대기"; kr: { code: string; name: string }[]
}
export interface PropagationResponse { as_of: string | null; waiting: PropRow[]; diverging: PropRow[]; leads: PropLead[] }

/** 돈의 흐름·스포트라이트 가설 — GET /api/spine/tw/flow (docs/specs/value-chain.md §11) */
export interface FlowRow {
  key: string; name: string; state: string | null; score: number; yoy: number | null; increment_usd: number | null; period: string | null
  increment_prev_usd?: number | null; increment_change_usd?: number | null
  kind: "flow" | "stock"; cross_agree: number | null; kr: string[]; kr_return_3m: number | null; attention: number; attention_prev: number
  why?: string | null; falsifier?: string | null
  obs_kind?: "direct" | "proxy"; disclosure_up?: number | null; disclosure_n?: number | null
  level_usd?: number | null
}
/** 금액 규모(§14) — 수요 칸 규모·증가액, 선별 추정 증가액(공급 칸 증가액을 사는 칸 규모 비례로 나눔, 거래액 아님) */
export interface FlowDemand { key: string; name: string; level_usd: number | null; increment_usd: number | null; level_note?: string | null }
export interface EdgeFlow { from: string; to: string; flow_usd: number | null; basis: "estimate"; buyer_level_imputed: boolean }
export interface FlowResponse {
  as_of: string | null; twd_usd: number; median_kr_return_3m: number | null; median_attention: number
  flows: FlowRow[]; spotlight: FlowRow[]; doubted: FlowRow[]; fading: FlowRow[]; needs_check?: FlowRow[]; nodes: FlowRow[]
  demands?: FlowDemand[]; edge_flows?: EdgeFlow[]
}

/** 시장 기대치(§15) — 사실(관측)과 분리. rev_growth는 소수(0.44 = +44%), 칸 합계·개정·차이는 % */
export interface ExpPeriod { rev_avg?: number | null; rev_growth?: number | null; analysts?: number | null; eps_avg?: number | null; eps_30d?: number | null; eps_90d?: number | null }
export interface ExpMember { symbol: string; name: string; currency?: string | null; snap_date: string; periods: Record<string, ExpPeriod>; rev_revision_30d?: number | null }
export interface ExpClaim {
  source: string; source_org?: string | null; published_at?: string | null; subject?: string | null; metric: string; target_period?: string | null
  value_low?: number | null; value_high?: number | null; unit?: string | null; direction?: string | null; quote?: string | null; url?: string | null
}
export interface ExpNode {
  name?: string | null; members: ExpMember[]; coverage: string; exp_0q?: number | null; exp_0y?: number | null; exp_1y?: number | null
  eps_rev_30d?: number | null; eps_rev_90d?: number | null; rev_rev_30d?: number | null; claims: ExpClaim[]; note?: string | null
  observed?: number | null; observed_period?: string | null; obs_kind?: string | null; gap_pp?: number | null
}
export interface ExpGapRow { key: string; name: string; observed: number; exp_0q: number; gap_pp: number; eps_rev_30d?: number | null; eps_rev_90d?: number | null }
export interface ExpectationsResponse { as_of: string | null; revision_base?: string | null; gap_pp: number; nodes: Record<string, ExpNode>; ahead: ExpGapRow[]; behind: ExpGapRow[] }

/** 트리 보고서(§16) — 루트에서 공급 쪽으로 타고 들어간 칸들(flow_usd = 부모 칸으로 가는 추정 증가액) */
export interface ChainTreeNode { key: string; name: string; parent: string | null; depth: number; flow_usd: number | null }
export interface ChainPreview { root: string; tree: ChainTreeNode[]; calls: Record<string, number>; models: Record<string, string> }
export interface ChainRef { ref: string; title?: string | null; url?: string | null; date?: string | null; kind?: string | null }
export interface ChainReport {
  id: number; root: string; status: "running" | "done" | "partial" | "error"; progress?: string | null; body?: string | null; analysis?: string | null; model?: string | null
  outline?: ChainOutline
  error?: string | null; created_at?: string | null; finished_at?: string | null; tree: ChainTreeNode[]; refs: ChainRef[]; missing: { key: string; name: string; error: string }[]
}
/** 목차 순서 — 재료는 언제나 bottom-up으로 모으고 글의 순서만 고른다 */
export type ChainOutline = "bottom_up" | "top_down"
export interface ChainReportItem { id: number; root: string; status: string; outline?: ChainOutline; created_at?: string | null; finished_at?: string | null }
/** 종목 추적 카드(docs/specs/stock-tracker.md) — 차트·기술적 신호·수급·이슈·내 원칙 조건. 국내 종목·미국 티커 */
export type TrackerKind = "price_below" | "price_above" | "close_below_ma" | "close_above_ma" | "manual"
export type TrackerRole = "entry" | "exit" | "check"
export interface TrackerCondition {
  id: number; stock_code: string; role: TrackerRole; kind: TrackerKind; level?: number | null; ma?: number | null; label: string; note?: string | null
  done: number; status: "met" | "not_met" | "pending" | "unknown"; distance_pct?: number | null; ref?: number | null
  /** 오늘 새로 충족(확인 항목은 오늘 확인) — 홈 › 내 종목 알림 줄 */
  newly_met?: boolean
}
export interface TrackerBar { t: string; o: number; h: number; l: number; c: number; v: number; ma20: number | null; ma60: number | null; ma120: number | null }
export interface TrackerView {
  /** us = 미국 일봉(us_prices) 기준 — 수급·공시 없음 */
  code: string; name: string; market?: "kr" | "us"; price: number | null; change_pct: number | null; as_of: string | null; source: "live" | "close" | null; last_close_date: string | null
  chart: { series: TrackerBar[] }
  technicals: {
    rsi14?: number | null; ma20_gap?: number | null; ma60_gap?: number | null; ma120_gap?: number | null; off_52w_high?: number | null; ret_1m?: number | null; ret_3m?: number | null
    overhead_pct?: number | null; support_pct?: number | null; rs?: number | null; volume_ratio?: number | null
    regime?: { posture?: string | null; reason?: string | null }; signals?: { date: string; label: string; id: string }[]; signals_as_of?: string | null; error?: string
  }
  flows: null | {
    as_of: string; days: number; foreign_5d: number; foreign_20d: number; inst_5d: number; inst_20d: number; indiv_5d: number; indiv_20d: number
    foreign_ratio: number | null; foreign_ratio_chg: number | null
  }
  issues: {
    disclosures: { date: string; title: string; url: string | null; key: boolean }[]; docs_7d: number
    docs: { id: number; title: string; published_at: string; source_type: string }[]; target_prices: { date: string; value: number; doc_id: number; title: string }[]
  }
  conditions: TrackerCondition[]
}

/** 추적 종목 전체의 조건 충족 요약(GET /api/spine/tracker/status, D-301) — 머리 줄 '충족 n'·알림 줄. 저장된 시세·조건만 읽는다 */
export interface TrackerStatusCondition { id: number; role: TrackerRole; label: string; status: TrackerCondition["status"]; newly_met: boolean }
export interface TrackerStatusItem { code: string; name: string; market: "kr" | "us"; as_of: string | null; met: number; newly_met: number; conditions: TrackerStatusCondition[] }
export interface TrackerStatus { items: TrackerStatusItem[]; met: number; newly_met: number }

/* ---------- 국면 이력 (docs/specs/market-regimes.md) — 규칙 판정, LLM 0 ---------- */
export type RegimeKind = 'bull' | 'bear'
export interface RegimePhase {
  kind: RegimeKind
  start: string
  end: string
  start_close: number
  end_close: number
  change_pct: number
  days: number
  confirm_date: string | null
  confirm_lag_days: number | null
  provisional: boolean
}
export interface RegimeCorrection { start: string; trough: string; end: string | null; drawdown_pct: number; near_threshold: boolean }
export interface RegimeTrend { state: 'up' | 'down'; start: string; end: string }
export interface RegimeRecession { start: string; end: string; open: boolean }
export interface RegimesResponse {
  as_of: string | null
  first_date: string | null
  fetched_at: string | null
  params: { bear: number; bull: number; correction: number; near: number; trend_months: number; version: string }
  index: { ticker: string; label: string }
  phases: RegimePhase[]
  corrections: RegimeCorrection[]
  trend: RegimeTrend[]
  recessions: RegimeRecession[]
  series: [string, number][]
  current: { kind: RegimeKind; start: string; close: number; from_peak_pct: number; from_trough_pct: number; trend: 'up' | 'down' | null } | null
}
export type BrkBenchKey = 'sp500tr' | 'sp500' | 'nasdaq'
export type BrkRange = '1y' | '3y' | '5y' | '10y' | '20y' | 'all'
export interface RegimeBand { kind: 'bear' | 'recession'; start: string; end: string; provisional: boolean }
export interface BrkPhase {
  kind: RegimeKind
  start: string
  end: string
  provisional: boolean
  clipped_start: string | null
  spx_change_pct: number
  confirm_date: string | null
  confirm_lag_days: number | null
  brk_pct: number
  bench_pct: number
  excess_pct: number
  beta: number | null
  beta_adj_pct: number | null
}
export interface BrkSummary { n: number; brk_wins: number; median_excess_pct: number | null; beta_adj_wins: number; beta_adj_n: number }
export interface BrkResponse {
  bench: { key: BrkBenchKey; ticker: string; label: string; dividends: boolean; first_date: string | null }
  brk_first_date: string | null
  range: BrkRange
  as_of: string | null
  start: string | null
  points: { date: string; brk_pct: number; bench_pct: number; rs: number }[]
  rolling: { date: string; brk_12m: number; bench_12m: number; excess_12m: number; beta_36m: number | null; beta_adj_12m: number | null }[]
  phases: BrkPhase[]
  summary: Partial<Record<RegimeKind, BrkSummary>>
  bands: RegimeBand[]
}
export interface RegimeCollectResponse {
  results: { key: string; status: 'ok' | 'skip' | 'error'; rows: number; period: string | null; error: string | null }[]
  collected_at: string
}

/* ---------- 지금 시장 읽기 — 네 층 (pipeline/era.py, docs/specs/market-regimes.md §8) ---------- */
export type EraHeat = 'hot' | 'normal' | 'cold'
export type EraOutcome = 'bear' | 'rebound' | 'correction' | 'false'
export interface EraEpisode {
  date: string
  outcome: EraOutcome
  drawdown_at: number
  min_after: number
  ret_after: number | null
  complete: boolean
  /** [켜진 뒤 거래일, 켜진 날 = 100 기준 지수] */
  path: [number, number][]
}
export interface EraSignalStats { bears_caught: number; bears_total: number; drawdown_at_median: number | null; remaining_median: number | null; false_per_decade: number; episodes: number; false: number }
export interface EraSignal {
  on: boolean
  since: string | null
  label: string
  rule: string
  stats: EraSignalStats
  episodes: EraEpisode[]
  median_path: Record<EraOutcome, [number, number][]>
}
export interface EraLayerState {
  available: boolean
  as_of: string
  close: number
  stage: 'none' | 'warn' | 'confirm'
  warn: EraSignal & { month_end: string; vs_sma_pct: number; provisional_on: boolean; provisional_vs_sma_pct: number }
  confirm: EraSignal & { new_low: boolean; last_new_low: string | null; slope_down: boolean; ma200_slope_pct: number }
  reference: { ret_12m: number; from_52w_high: number }
  current_path: [number, number][]
  recession_hint: { inverted_24m: boolean | null; min_24m: number | null }
}
export interface EraLayerMeaning {
  available: boolean
  as_of: string | null
  corr_36m: number | null
  corr_250d: number | null
  regime: 'inflation' | 'disinflation' | null
  cpi_yoy: number | null
  cpi_month: string | null
  rate_change_6m: { us10y: number; bill3m: number | null }
  conditional_flag: boolean
  rule: string
  research: { a: string; b: string; note: string }
  decades: Record<string, number>
  corr_series: [string, number][]
}
export interface EraTempItem { key: string; label: string; value: number | string | null; unit: string; state: EraHeat; basis: string; source: string }
export interface EraJudged { key: string; label: string; state: EraHeat | null; note: string | null; updated_at: string | null }
export interface EraSource { doc_id: number | null; title: string; date: string; url: string | null }
export interface EraPremise {
  key: string
  claim: string
  who: string
  kind: string
  evidence: string[]
  status: 'supports' | 'challenges' | 'mixed' | 'untestable' | 'nodata' | null
  rule: string
  sources: EraSource[]
  who_people?: WhoPerson[]   // '누가'를 사람·기관으로 나눈 것(인물 대응 표, ia-redesign §4.23)
}
export interface EraStateResponse {
  state: EraLayerState
  meaning: EraLayerMeaning
  temperature: { items: EraTempItem[]; judged: EraJudged[]; hot: number; cold: number; normal: number; verdict: 'hot' | 'cold' | 'balanced'; missing: string[] }
  premises: EraPremise[]
  latest_memos: { doc_id: number; title: string; date: string }[]
  generated_at: string
}
export interface EraCommentary { body: string | null; created_at: string | null; model: string | null; stale: boolean }

/* ---------- 시장 프라이싱 원장 (docs/specs/pricing-ledger.md) ---------- */
export type PricingStance = 'present' | 'stronger' | 'weaker' | 'contested'
export type PricingStatus = 'new' | 'stronger' | 'weaker' | 'faded' | 'ongoing' | 'dormant'
export interface PricingPrice { key: string; label: string; unit: string; value: number | null; as_of: string | null; chg_1w: number | null; chg_4w: number | null; mode: 'bp' | 'pct' | 'pt' }
export interface PricingSourceRef { publisher: string | null; title: string | null; url: string | null; doc_id: number | null }
export interface PricingClaim {
  id: number
  statement: string
  theme: string
  first_seen: string
  last_seen: string
  days_seen: number
  status: PricingStatus
  dates: [string, PricingStance][]
  latest: { date: string; stance: PricingStance; evidence: string | null; sources: PricingSourceRef[] } | null
  related: string[]
}
export interface PricingResponse {
  days: string[]
  as_of: string | null
  extracted_days: number
  pending: number
  prices: PricingPrice[]
  claims: PricingClaim[]
  summary: Record<'new' | 'stronger' | 'weaker' | 'faded', string[]>
}

/** GET /api/spine/admin/runtime — 실행 중인 백엔드가 최신 코드인가(재시작 필요 감지) */
export interface RuntimeStatus { started_at: string; code_changed_at: string | null; changed_file: string | null; stale: boolean; stale_minutes: number }

/* ---------- 관측 (docs/specs/observability.md) — GET /api/spine/admin/observe ---------- */
export interface ObserveJobRow { job: string; name: string; n: number; ok: number | null; err: number | null; part: number | null; avg_ms?: number | null; last?: string | null }
export interface ObserveApiRow { endpoint: string; count: number; errors_5xx: number; err_rate: number; avg_ms: number | null; p95_ms: number | null; max_ms: number }
export interface ObserveSummary {
  days: number; generated_at: string
  jobs: { total: { runs: number; ok: number; err: number; partial: number }; failing: ObserveJobRow[]
    streaks: { job: string; name: string; streak: number; last: string }[]; chronic: { job: string; name: string; runs: number }[]; table: ObserveJobRow[] }
  api: { since: string | null; requests: number; errors_5xx: number; worst_errors: ObserveApiRow[]; slowest: ObserveApiRow[]; busiest: ObserveApiRow[] }
  client_errors: { endpoint: string; field: string | null; kind: string; count: number; last_seen: string }[]
  freshness: { label: string; detail: string }[]
  costs: { usd: number; calls: number; prev_usd: number; change_pct: number | null
    by_job: { job: string; name: string; usd: number | null; calls: number; failed: number | null; cache_pct: number | null; share: number }[]
    daily: { day: string; usd: number | null }[] }
  usage: { since: string | null; visits: number; sessions: number; screens: { name: string; visits: number; avg_dwell_ms: number | null }[]
    paths: { ref: string; name: string; n: number }[]; actions: { name: string; n: number }[]; dropped: string[] }
  value: { opens: { name: string; n: number; uniq: number }[]; expectation_grades: { hit: number; underweighted: number; noise: number; missed: number } }
}

/* ---------- Market Today (docs/specs/market-today.md) — GET /api/spine/market-today ---------- */
export interface TodaySource { ref: string; kind: string; publisher: string | null; title: string | null; url: string | null; doc_id: number | null; published_at: string | null; echo: number }
export interface TodayIndexAt { value: number; change_pct: number | null; at: string }
/** 화두에 걸린 내러티브 (ia-redesign §9.1) — rule 1 태그 일치 · 2 자료 겹침 + 태그 부분 일치 · 3 자료 겹침 */
export interface TopicNarrative { topic: string; narrative_id: number; version: number; created_at: string | null; rule: number; doc_overlap: number }
export interface TodayTopic { title: string; body: string; tags: string[]; continuing: boolean; echo: number; refs: string[]; sources: TodaySource[]; narratives: TopicNarrative[] }
export interface MarketToday {
  trade_date: string | null
  slots: { slot: string; label: string; created_at: string; topics: number }[]
  current: {
    slot: string; label: string; window_start: string; window_end: string; created_at: string; doc_count: number; telegram: number; news: number
    /** 회차 시점 시장 상태 — 코스피·코스닥 값과 전일 대비, 코스피 5분 경로 */
    market: { kospi?: TodayIndexAt | null; kosdaq?: TodayIndexAt | null; path: [string, number][] } | null
    /** 내러티브 연결을 계산했는가 — 아니면 칩 줄을 그리지 않는다 */
    links_ready: boolean
    topics: TodayTopic[]
  } | null
  next_slot: string | null
  /** 앞뒤로 회차가 있는 날(‹ › 이동). next_date는 없고 오늘보다 앞이면 오늘 */
  prev_date?: string | null
  next_date?: string | null
}

/* ---------- 화두 → 내러티브 타임라인·후보 (ia-redesign §9) ---------- */
export type TimelineCellState = "linked" | "unlinked" | "scheduled" | "absent"
export interface NarrativeMarketToday {
  topic: string; narrative_id: number
  collected_since: string | null
  days: { trade_date: string; cells: { slot: string; label: string; state: string; wrap: boolean }[] }[]
  items: { mt_id: number; trade_date: string; slot: string; label: string; title: string; rule: number; doc_overlap: number; wrap: boolean }[]
  week_topics: number; week_sessions: number; boost: boolean
}
export interface NarrativeCandidate {
  tag: string; name: string
  /** pending 후보 · approved 승인(첫 버전 대기) · watching 관찰 중 */
  status: string
  first_seen: string; last_seen: string; days: number; sessions: number; sources: number; tags: string[]
  session_list: { mt_id: number; trade_date: string; slot: string; label: string }[]
  titles: string[]; linked: string[]
  merge_into: { topic: string; overlap: number; narrative_id: number; version: number; created_at: string | null } | null
  narrative_topic: string | null; attempt: string | null
}
export interface NarrativeCandidates { items: NarrativeCandidate[] }
export interface CandidateAction { tag: string; status: string; mode: string | null; narrative_topic: string | null; dismissed_until: string | null }

/* ---------- 기업 관련 자료 (GET /api/spine/feed/company-evidence) ---------- */
export interface EvidenceItem {
  id: string
  doc_id: number | null
  title: string
  url: string
  excerpt: string
  source_type: string
  publisher: string
  published_at: string
  local_date: string
  time_precision: 'date' | 'time'
  status: 'within' | 'after' | 'uncertain'
  relation: string
}
export interface EvidenceResponse {
  items: EvidenceItem[]
  total: number
  page: number
  size: number
  has_more: boolean
  as_of: string
  coverage: { source: string; first: string; last: string; count: number }[]
  undated_count: number
  uncertain_count: number
  timezone: string
  /** 최근 30일 언급 흐름 — 출처·검색어와 무관하게 이 기업 자료 전체(시장 시간대 날짜) */
  flow: EvidenceFlow
}
export interface EvidenceFlow {
  start: string
  end: string
  days: { date: string; count: number }[]
  sources: { source: string; count: number }[]
}
export interface EvidenceRange {
  start?: string
  end?: string
  cutoff?: 'end' | 'close'
  after?: boolean
}

/* ---------- 관리자 › 작업·신선도 · 자동 정리 (ia-redesign §4.31) ---------- */
/** GET /api/spine/admin/jobs — ran_at은 UTC(SQLite datetime('now')) */
export interface AdminJobStatus {
  name: string; label: string; description: string; entrypoint: string; enabled: boolean
  last_run: { status: string; summary: string | null; duration_ms: number | null; ran_at: string } | null
}
/** GET /api/spine/admin/health — 데이터 신선도(D-222) */
export interface AdminHealthItem {
  key: string; label: string; kind: string; owner: string; critical: boolean
  latest: string | null; expected: string | null; status: string; detail: string
}
/** GET /api/spine/admin/runs */
export interface AdminJobRun { job: string; status: string; summary: string | null; duration_ms: number | null; ran_at: string }
/** GET /api/spine/curation — 정리 작업 자동 판정 기록(D-294·D-295). decided_at은 UTC */
export interface CurationEntry {
  kind: string; target_id: number; title: string; verdict: string; rule: string | null; applied: boolean; decided_at: string | null
}
export interface CurationLog { apply_enabled: boolean; counts: Record<string, Record<string, number>>; items: CurationEntry[] }

/** GET /api/spine/causal/activity — 최근 n일 새로 생기거나 갱신된 인과 그래프 노드 + 수혜 후보(D-035) */
export interface GraphActivityBeneficiary { stock_code: string; name: string; rs_short: number | null }
export interface GraphActivityNode { id: number; name: string; type: string; is_new: boolean; new_edges: number; beneficiaries: GraphActivityBeneficiary[] }
