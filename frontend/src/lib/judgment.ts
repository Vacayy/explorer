/**
 * Thesis › 내 판단(ia-redesign §4.10·§4.27)의 순수 계산 — 보기 전환·리포트 레이팅 말·작성 이후 변화·접을 본문.
 * 화면(components/thesis/*, explore/ReportView, knowledge/QuestionDetail)과 테스트가 같이 쓴다.
 */

/* ---------- 보기 전환: 질문 · 논지 감사 · 리포트 · 지표 보드 ---------- */
export type JudgmentView = "questions" | "thesis" | "report" | "proxies"

export const JUDGMENT_VIEWS: { key: JudgmentView; label: string; to: string }[] = [
  { key: "questions", label: "질문", to: "/questions" },
  { key: "thesis", label: "논지 감사", to: "/thesis" },
  { key: "report", label: "리포트", to: "/report" },
  { key: "proxies", label: "지표 보드", to: "/questions?view=proxies" },
]

/** 주소 → 지금 보기. 지표 보드는 /questions?view=proxies(옛 /proxy-boards·컨콜 ?view=proxies는 리다이렉트, §10.6) */
export function judgmentView(pathname: string, search: string): JudgmentView {
  if (pathname.startsWith("/thesis")) return "thesis"
  if (pathname.startsWith("/report")) return "report"
  if (pathname.startsWith("/proxy-boards")) return "proxies"
  if (pathname === "/questions" && new URLSearchParams(search).get("view") === "proxies") return "proxies"
  return "questions"
}

/** 옛 지표 주소(/proxy-boards?board=1, /follow/transcripts?view=proxies) → /questions?view=proxies(나머지 쿼리는 그대로) */
export function proxiesUrl(search: string): string {
  const p = new URLSearchParams(search)
  p.delete("view")
  const rest = p.toString()
  return `/questions?view=proxies${rest ? `&${rest}` : ""}`
}

/* ---------- 리포트 레이팅 — 매매 권유 표현을 비대칭 판단으로 (11-04 결정 ①) ---------- */
const RATING_WORDS: Record<string, string> = {
  "Strong Buy": "상방 우위(비대칭 큼)",
  Buy: "상방 우위",
  Hold: "중립",
  Sell: "하방 우위",
}

/** 옛 영문 레이팅(Strong Buy·Buy·Hold·Sell)을 새 말로(D-307: Hold → 중립). 새 말·모르는 값은 그대로 */
export function ratingLabel(rating: string | null | undefined): string | null {
  if (!rating) return null
  return RATING_WORDS[rating] ?? rating
}

/** 레이팅 방향 — 색만 정한다(상방 = up, 하방 = down) */
export function ratingTone(rating: string | null | undefined): "up-strong" | "up" | "down" | "neutral" {
  const l = ratingLabel(rating)
  if (l === "상방 우위(비대칭 큼)") return "up-strong"
  if (l === "상방 우위") return "up"
  if (l === "하방 우위") return "down"
  return "neutral"
}

/** 옛 리포트 본문에 박힌 영문 레이팅을 새 말로 바꿔 보인다(저장 원문은 그대로). 'Buy-side'·'Sell-off' 같은 단어는 건드리지 않는다 */
export function relabelRatings(text: string): string {
  return text
    .replace(/\bStrong Buy\b/g, RATING_WORDS["Strong Buy"])
    .replace(/\bBuy\b(?![-\w])/g, RATING_WORDS.Buy)
    .replace(/\bHold\b(?![-\w])/g, RATING_WORDS.Hold)
    .replace(/\bSell\b(?![-\w])/g, RATING_WORDS.Sell)
}

/* ---------- 리포트 '작성 이후 변화' — 관측이지 판정이 아니다 ---------- */
export interface SincePoint { date: string; value: number }
export interface SinceChange { fromDate: string; from: number; toDate: string; to: number; pct: number }

/** 작성일(그날 포함 이전 마지막 값) → 최신 값. 작성일 이전 값이 없거나 작성 뒤 새 값이 없으면 null */
export function sinceChange(series: SincePoint[], since: string): SinceChange | null {
  const day = since.slice(0, 10)
  const xs = [...series].filter((p) => p.value != null && Number.isFinite(p.value)).sort((a, b) => a.date.localeCompare(b.date))
  const base = [...xs].reverse().find((p) => p.date.slice(0, 10) <= day)
  const last = xs[xs.length - 1]
  if (!base || !last || last.date.slice(0, 10) <= day || !base.value) return null
  return { fromDate: base.date.slice(0, 10), from: base.value, toDate: last.date.slice(0, 10), to: last.value, pct: (last.value / base.value - 1) * 100 }
}

/* ---------- 접을 본문 ---------- */
const REPORT_HEAD = /^(결론|핵심 질문|투자 포인트 요약)\s*$/

/** 리포트 본문을 앞(결론·핵심 질문·투자 포인트 요약)과 접을 뒤(산업 분석 이하 '## ' 섹션)로 나눈다 */
export function splitReportBody(md: string): { head: string; rest: string } {
  const lines = md.split("\n")
  const at = lines.findIndex((l) => /^## /.test(l) && !REPORT_HEAD.test(l.slice(3).trim()))
  if (at <= 0) return { head: md, rest: "" }
  return { head: lines.slice(0, at).join("\n").trimEnd(), rest: lines.slice(at).join("\n").trim() }
}

/** 접을 리포트 섹션 이름들(펼치기 버튼 문구) */
export function reportSectionNames(rest: string): string[] {
  return rest.split("\n").filter((l) => /^## /.test(l)).map((l) => l.slice(3).trim())
}

/** 질문 종합에서 '아직 미판정'·'…흔들릴 조건' 섹션부터는 접는다(§4.27 A 제안) */
export function splitSynthesis(md: string): { main: string; folded: string } {
  const lines = md.split("\n")
  const at = lines.findIndex((l) => /^#{2,4}\s/.test(l) && /미판정|흔들/.test(l))
  if (at < 0) return { main: md, folded: "" }
  return { main: lines.slice(0, at).join("\n").trimEnd(), folded: lines.slice(at).join("\n").trim() }
}

/** 시나리오 칩 말 = 데이터 값 그대로 '수혜·피해'(D-307, 4f의 '유리·불리' 되돌림). 그 밖의 값은 null */
export function scenarioSide(rel: string | null | undefined): "수혜" | "피해" | null {
  return rel === "수혜" || rel === "피해" ? rel : null
}
