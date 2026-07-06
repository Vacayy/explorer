/**
 * Format a number in Korean style (억, 조 units).
 * Input is in 원 (won).
 */
export function formatKrw(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-"
  const num = typeof value === "string" ? parseFloat(value.replace(/,/g, "")) : value
  if (isNaN(num)) return "-"

  const absNum = Math.abs(num)
  const sign = num < 0 ? "-" : ""

  const eok = absNum / 1e8
  if (eok >= 10000) {
    const jo = eok / 10000
    if (jo >= 100) return `${sign}${Math.round(jo).toLocaleString("ko-KR")}조`
    if (jo >= 10) return `${sign}${jo.toFixed(1)}조`
    return `${sign}${jo.toFixed(2)}조`
  }
  if (eok >= 1) {
    if (eok >= 1000) return `${sign}${Math.round(eok).toLocaleString("ko-KR")}억`
    if (eok >= 100) return `${sign}${Math.round(eok).toLocaleString("ko-KR")}억`
    if (eok >= 10) return `${sign}${eok.toFixed(0)}억`
    return `${sign}${eok.toFixed(1)}억`
  }

  const man = absNum / 10000
  if (man >= 1) return `${sign}${Math.round(man).toLocaleString("ko-KR")}만`
  return num.toLocaleString("ko-KR")
}

/**
 * Format DART financial amount (stored as string of raw won amount).
 * Shows in 조/억/만 with comma-separated numbers for readability.
 * e.g. 84444745007 → "844억", 22242526961 → "222억"
 */
export function formatDartAmount(value: string | null | undefined): string {
  if (!value || value === "None" || value === "null") return "-"
  const num = parseFloat(value.replace(/,/g, ""))
  if (isNaN(num)) return "-"
  return formatKrw(num)
}

/**
 * Format as percentage with sign indicator.
 */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(1)}%`
}

/**
 * Format plain number with Korean locale commas.
 */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  return value.toLocaleString("ko-KR")
}

/**
 * Format number in 억 for chart axis/labels. Returns compact string.
 * e.g. 844 → "844", 1234 → "1,234"
 */
export function formatEok(value: number | null): string {
  if (value === null) return "-"
  return value.toLocaleString("ko-KR")
}

/**
 * Format USD amount with compact suffix (B/M/K).
 */
export function formatUsd(value: number): string {
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `$${(value / 1e3).toFixed(1)}K`
  return `$${value.toFixed(0)}`
}

/**
 * Format price with appropriate decimal places.
 */
export function formatPrice(value: number): string {
  if (value >= 1000) return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
  if (value >= 1) return `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`
  return `$${value.toFixed(4)}`
}

/**
 * Format funding rate as percentage.
 */
export function formatFundingRate(rate: string | number): string {
  const num = typeof rate === "string" ? parseFloat(rate) : rate
  return `${(num * 100).toFixed(4)}%`
}

/** ISO 시각 → 상대 시간 표기 ("3분 전", "2시간 전", "어제", "6/28") */
export function formatRelativeTime(iso: string): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "-";
  const diffMs = Date.now() - t;
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const day = Math.floor(hr / 24);
  if (day === 1) return "어제";
  if (day < 7) return `${day}일 전`;
  const d = new Date(t);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
