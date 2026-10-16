import type { TimelineChannel } from "@/types"

/**
 * 캔버스 순수 함수 (docs/specs/canvas.md) — React·DOM 의존 없음(테스트 대상).
 */

/** Explorer 시스템 소스 종류 — 소스 id 접두사 */
export const SYSTEM_KIND_LABEL: Record<string, string> = {
  company: "기업 요약", transcript: "컨콜", person: "인물 요약",
  narrative: "내러티브", report: "리포트", scenario: "파급 분석", trade: "수출입",
}
/** 하위 묶음으로 접는 종류(항목이 많다). 나머지는 Explorer 묶음 바로 안에 한 줄씩 */
const NESTED = ["company", "transcript", "person"]

export interface DirectoryGroup { kind: string; label: string; items: TimelineChannel[]; unread: number }
export interface Directory {
  /** 팔로우한 사람 소스(텔레그램·블로그·유튜브) — 맨 위 */
  human: TimelineChannel[]
  explorer: { singles: TimelineChannel[]; groups: DirectoryGroup[]; count: number; unread: number }
}

const sum = (xs: TimelineChannel[]) => xs.reduce((n, x) => n + x.unread, 0)
export const systemKind = (id: string) => id.split(":")[0]
export const isSystemChannel = (id: string) => Object.hasOwn(SYSTEM_KIND_LABEL, systemKind(id))

/** 소스 디렉터리 → 사람 소스 먼저, 시스템 항목은 'Explorer' 묶음 안 종류별로. 각 목록의 원래 순서(최신순)는 유지 */
export function groupDirectory(items: TimelineChannel[]): Directory {
  const human = items.filter(i => i.platform !== "system")
  const system = items.filter(i => i.platform === "system")
  const groups = NESTED.map(kind => {
    const xs = system.filter(i => systemKind(i.id) === kind)
    return { kind, label: SYSTEM_KIND_LABEL[kind], items: xs, unread: sum(xs) }
  }).filter(g => g.items.length > 0)
  const singles = system.filter(i => !NESTED.includes(systemKind(i.id)))
  return { human, explorer: { singles, groups, count: system.length, unread: sum(system) } }
}

/**
 * 'AI가 최근 만든 것' 기간 표기 — 응답이 상한(limit)에 닿으면 '지난 N일'이 거짓이 된다(30건이 약 2.5일).
 * 상한에 닿았으면 실제로 보이는 가장 오래된 시각을, 아니면 기간 전체를 말한다.
 */
export function aiCoverageLabel(createdAts: string[], limit: number, days: number,
  fmt: (t: string) => string = t => t.slice(5, 16).replace("T", " ")): string {
  if (createdAts.length === 0) return `지난 ${days}일`
  if (createdAts.length < limit) return `지난 ${days}일 · ${createdAts.length}건`
  const oldest = [...createdAts].sort()[0]
  return `최근 ${limit}건 · ${fmt(oldest)} 이후`
}
