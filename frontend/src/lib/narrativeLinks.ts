/**
 * Market Today 화두 → 내러티브 연결 공용 순수 로직 (ia-redesign §9).
 */
import { kstDay } from '@/lib/bigPicture'
import type { TopicNarrative } from '@/types'

export const RULE_LABEL: Record<number, string> = { 1: '태그 일치', 2: '자료 겹침 + 태그 부분 일치', 3: '자료 겹침' }
export const CHIP_LIMIT = 2

/** 칩 줄 — 앞 2개만 칩, 나머지는 +N으로 접는다(서버가 규칙 → 겹친 문서 수 순으로 준다) */
export function chipLine(items: TopicNarrative[]): { shown: TopicNarrative[]; rest: TopicNarrative[] } {
  return { shown: items.slice(0, CHIP_LIMIT), rest: items.slice(CHIP_LIMIT) }
}

/** 칩 툴팁 두 줄 — 어떤 규칙으로·출처 몇 건 / 서사 버전·갱신일 */
export function chipTip(n: TopicNarrative): [string, string] {
  return [`${RULE_LABEL[n.rule] ?? '연결'} · 출처 ${n.doc_overlap}건 겹침`, `서사 v${n.version} · ${kstDay(n.created_at)} 갱신`]
}

/** 'YYYY-MM-DD' 거래일 → 'M/D' */
export function mdDate(d: string | null | undefined): string {
  if (!d) return '-'
  const [, m, day] = d.split('-')
  return `${Number(m)}/${Number(day)}`
}

export const narrativeHref = (topic: string) => `/narrative?topic=${encodeURIComponent(topic)}`
