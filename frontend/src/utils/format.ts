/**
 * Format a number in Korean style (억, 조 units).
 * Input is in 원 (won).
 */
export function formatKrw(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-"
  const num = typeof value === "string" ? parseFloat(value.replace(/,/g, "")) : value
  if (isNaN(num)) return "-"

  const absNum = Math.abs(num)
  const sign = num < 0 ? MINUS : ""

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

/** 부호 문자 — 양수 '+', 음수 '−'(U+2212, D-320), 표시 자릿수로 0이 되면 부호 없음 */
export const MINUS = "\u2212"
function signOf(value: number, digits: number): string {
  const shown = Number(value.toFixed(digits))
  return shown > 0 ? "+" : shown < 0 ? MINUS : ""
}

/**
 * Format as percentage with sign indicator (+1.5% · −0.5%).
 */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  return `${signOf(value, 1)}${Math.abs(value).toFixed(1)}%`
}

/**
 * Format a z-score as signed sigma multiple (e.g. +1.4σ) — 칸 상태의 '평소 변동 대비' 크기.
 */
export function formatSigma(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  return `${signOf(value, 1)}${Math.abs(value).toFixed(1)}σ`
}

/**
 * Format a percentage-point change with sign (e.g. +0.35%p) — 금리 등 이미 %인 값의 변동.
 */
export function formatPp(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "-"
  return `${signOf(value, digits)}${Math.abs(value).toFixed(digits)}%p`
}

/**
 * PER·선행 PER — 소수 1자리 + '배'(docs/policies/number-formatting.md). null이면 '-'.
 */
export function formatPer(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  return `${value.toFixed(1)}배`
}

/**
 * Format a share/ratio as percentage without a sign (e.g. 15.3%). Use formatPercent for changes.
 */
export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  return `${value.toFixed(1)}%`
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
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`
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
 * 종목 가격 — 국내 '72,900원', 미국 '$479.54'(소수 2자리). null이면 '-'.
 */
export function formatStockPrice(value: number | null | undefined, market?: string | null): string {
  if (value === null || value === undefined) return "-"
  if (market === "us") return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  return `${formatNumber(value)}원`
}

/**
 * Format funding rate as percentage.
 */
export function formatFundingRate(rate: string | number): string {
  const num = typeof rate === "string" ? parseFloat(rate) : rate
  return `${(num * 100).toFixed(4)}%`
}

/** UTC 시각(SQLite·ISO) → KST "MM-DD HH:MM" 표기 */
export function formatKstDateTime(utc: string | null | undefined): string {
  if (!utc) return "-";
  const iso = utc.includes("T") ? utc : utc.replace(" ", "T");
  const d = new Date(iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z");
  if (Number.isNaN(d.getTime())) return "-";
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(d).map(x => [x.type, x.value]));
  return `${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

/** UTC 시각(SQLite·ISO) → KST "MM/DD HH:MM", time=false면 "MM/DD" (대화 목록·답변 머리) */
export function formatKstSlashDate(utc: string | null | undefined, time = true): string {
  const day = utc && /^\d{4}-(\d{2})-(\d{2})$/.exec(utc);
  if (day) return `${day[1]}/${day[2]}`;
  const s = formatKstDateTime(utc);
  if (s === "-") return s;
  const [md, hm] = s.split(" ");
  const slash = md.replace("-", "/");
  return time ? `${slash} ${hm}` : slash;
}

/** 시각 → KST "11월 4일 수요일" (홈 대시보드 머리) */
export function formatKstLongDate(d: Date = new Date()): string {
  return d.toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric", weekday: "long" });
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

/**
 * Format an interest-rate level with 2 decimals (e.g. 7.45%) — 채권 수익률·국채 금리 수준.
 */
export function formatYield(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  return `${value.toFixed(2)}%`
}

/**
 * Format basis points (e.g. 239, signed change +71 / -6). 0은 부호 없이.
 */
export function formatBp(value: number | null | undefined, signed = false): string {
  if (value === null || value === undefined) return "-"
  const rounded = Math.round(value)
  const sign = rounded < 0 ? MINUS : signed && rounded > 0 ? "+" : ""
  return `${sign}${Math.abs(rounded).toLocaleString("ko-KR")}`
}

/**
 * Format an index level or point value with two decimals (e.g. 5,779.14 · 16.46).
 */
export function formatLevel(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-"
  return value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** DB 시각(SQLite UTC 'YYYY-MM-DD HH:MM:SS' 또는 시간대 붙은 ISO) → 상대 표기. 비면 "-" */
export function formatDbRelative(value: string | null | undefined): string {
  if (!value) return "-"
  const iso = value.includes("T") ? value : value.replace(" ", "T") + "Z"
  return formatRelativeTime(iso)
}

/** DB 시각이 지금부터 며칠 전인가 (UTC 기준). 비면 Infinity */
export function dbAgeDays(value: string | null | undefined): number {
  if (!value) return Infinity
  const t = new Date(value.includes("T") ? value : value.replace(" ", "T") + "Z").getTime()
  return Number.isNaN(t) ? Infinity : (Date.now() - t) / 86_400_000
}

/** 대만 월매출(원천 단위 천 TWD) → 억 TWD 표기. 1,000억 이상은 정수, 그 아래는 소수 1자리. 비면 "-" */
export function formatTwdEok(thousand: number | null | undefined): string {
  if (thousand === null || thousand === undefined) return "-"
  const eok = thousand / 100_000
  return Math.abs(eok) >= 1000
    ? `${Math.round(eok).toLocaleString("ko-KR")}억`
    : `${eok.toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}억`
}

/** 건수 줄임 — 1천 이상은 천 단위 소수 1자리('1.1천'·'25.3천', 피드 소스 칩). null은 '-' */
export function formatCountShort(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  if (value >= 1000) return `${(value / 1000).toFixed(1)}천`
  return String(value)
}

/** 원 단위 주가를 축 눈금용으로 짧게 — 1만 이상은 '82만', 그 아래는 천 단위 쉼표 */
export function formatWonShort(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value >= 10_000 ? `${formatNumber(Math.round(value / 10_000))}만` : formatNumber(Math.round(value))
}

/** 소요 시간 ms → "3.1초" (관리자 작업·실행 내역) */
export function formatSeconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  return `${(ms / 1000).toFixed(1)}초`;
}
