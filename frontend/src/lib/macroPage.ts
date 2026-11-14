/**
 * 홈 › 매크로(ia-redesign §4.16·§4.28)의 순수 판정 — 화면 컴포넌트와 테스트가 같이 쓴다.
 */

/** 국면 이력 자동 첫 수집 — 조회가 끝났고 이력이 비어 있고 이번 페이지 수명에서 아직 시도하지 않았을 때만 */
export function shouldAutoCollect(s: { loaded: boolean; empty: boolean; tried: boolean; pending: boolean }): boolean {
  return s.loaded && s.empty && !s.tried && !s.pending
}

/** AI 해설 본문을 첫 단락(## 한 줄 요약)과 나머지로 나눈다. 첫 제목 줄은 뺀 본문만 lead로 */
export function splitCommentary(body: string): { lead: string; rest: string } {
  const text = body.trim()
  const start = text.startsWith("## ") ? (text.indexOf("\n") + 1 || text.length) : 0
  const next = text.indexOf("\n## ", start)
  return next < 0 ? { lead: text.slice(start).trim(), rest: "" } : { lead: text.slice(start, next).trim(), rest: text.slice(next + 1).trim() }
}

export type Position = "높음" | "보통" | "낮음"

/**
 * 리스크 타일의 장기 위치 배지 — 최근 5년(관측이 더 짧으면 있는 만큼) 안에서 지금 값의 백분위.
 * 상위 20% 이상 '높음', 하위 20% 이하 '낮음'. 관측 연수는 정직하게 내림한 값으로 붙인다.
 */
export function longRangePosition(points: [string, number][], value: number | null, asOf: string | null): { position: Position; years: number } | null {
  if (value == null || !asOf || points.length < 20) return null
  const cutoff = `${Number(asOf.slice(0, 4)) - 5}${asOf.slice(4)}`
  const window = points.filter(([d]) => d >= cutoff)
  if (window.length < 20) return null
  const years = Math.min(5, Math.max(1, Math.floor((Date.parse(asOf) - Date.parse(window[0][0])) / (365.25 * 86_400_000) + 0.05)))
  const rank = window.filter(([, v]) => v <= value).length / window.length
  return { position: rank >= 0.8 ? "높음" : rank <= 0.2 ? "낮음" : "보통", years }
}

/** CNN 공포·탐욕 구간 */
export function fearGreedZone(v: number | null): string | null {
  if (v == null) return null
  return v < 25 ? "극단적 공포" : v < 45 ? "공포" : v <= 55 ? "중립" : v <= 75 ? "탐욕" : "극단적 탐욕"
}

/** 최근 n개월 관측만 — 타일 추이선 */
export function lastMonths(points: [string, number][], asOf: string | null, months: number): [string, number][] {
  if (!asOf) return points
  const d = new Date(`${asOf}T00:00:00Z`)
  d.setUTCMonth(d.getUTCMonth() - months)
  const cutoff = d.toISOString().slice(0, 10)
  return points.filter(([t]) => t >= cutoff)
}

/** 리다이렉트 대상에 지금 쿼리를 붙인다 — 해시는 쿼리 뒤로 (`/home/macro#history` + `?a=1` → `/home/macro?a=1#history`) */
export function withSearch(to: string, search: string): string {
  const i = to.indexOf("#")
  return i < 0 ? `${to}${search}` : `${to.slice(0, i)}${search}${to.slice(i)}`
}
