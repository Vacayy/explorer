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
