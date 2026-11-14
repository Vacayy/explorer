import type { AnalysisRun } from '@/components/analysis/types'
import { formatKstDateTime, formatNumber, formatRelativeTime } from '@/utils/format'

/**
 * 종목 발견 › 이전 검색 시트 (ia-redesign §4.24 Discover-History).
 * 조건 검색은 질문 원문 대신 조건 이름 나열을 제목으로 쓴다(원문은 거의 같은 문장으로 시작해 서로 구분되지 않는다). 문장 검색은 원문 그대로.
 */
export type RunFilter = 'all' | 'matched' | 'empty' | 'error'
export const RUN_FILTERS: readonly { id: RunFilter; label: string }[] = [
  { id: 'all', label: '전체' }, { id: 'matched', label: '후보 있음' }, { id: 'empty', label: '후보 없음' }, { id: 'error', label: '오류' },
]
const FAILED = new Set(['failed', 'blocked', 'interrupted', 'cancelled'])

/** 조건 이름 나열(카탈로그 조건 검색) 또는 질문 첫 줄(문장 검색) */
export function runTitle(run: Pick<AnalysisRun, 'question' | 'spec' | 'result'>, labels: Readonly<Record<string, string>>): string {
  const conditions = run.spec?.mode === 'catalog' && !run.spec.expression ? run.spec.strategy_conditions ?? [] : []
  if (conditions.length) {
    const fromResult = Object.fromEntries((run.result?.strategy_definitions ?? []).map(d => [d.id, d.label]))
    return conditions.map(c => labels[c.strategy_id] ?? fromResult[c.strategy_id] ?? c.strategy_id).join(' · ')
  }
  return run.question.split('\n').map(line => line.replace(/^[-\s]+/, '').trim()).filter(Boolean).join(' ')
}

export function runOutcome(run: Pick<AnalysisRun, 'status' | 'result'>): Exclude<RunFilter, 'all'> | 'pending' {
  if (run.result) return run.result.counts.matched > 0 ? 'matched' : 'empty'
  return FAILED.has(run.status) ? 'error' : 'pending'
}

/** 검색 범위 — 국내 전체 · 시총 300억+ · 지정 9종목 */
export function runScope(run: Pick<AnalysisRun, 'spec'>): string {
  const spec = run.spec
  if (!spec) return '문장 검색'
  const parts = [spec.market === 'all' ? '국내 전체' : spec.market]
  if (spec.min_market_cap > 0 && spec.mode === 'catalog') parts.push(`시총 ${formatNumber(Math.round(spec.min_market_cap / 100_000_000))}억+`)
  if (spec.universe_codes?.length) parts.push(`지정 ${formatNumber(spec.universe_codes.length)}종목`)
  return parts.join(' · ')
}

const kstDay = (iso: string) => new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric' }).format(new Date(iso))

/** 오늘~6일 전은 상대 시각, 그 이전은 날짜·시각 */
export function runWhen(iso: string, now = Date.now()): string {
  const age = now - new Date(iso).getTime()
  return age < 7 * 86_400_000 ? formatRelativeTime(iso) : formatKstDateTime(iso).replace('-', '/')
}

/** 날짜별 묶음(실행 순서 유지) */
export function groupRunsByDay<T extends Pick<AnalysisRun, 'created_at'>>(runs: readonly T[]): { day: string; items: T[] }[] {
  const groups: { day: string; items: T[] }[] = []
  for (const run of runs) {
    const day = kstDay(run.created_at)
    const last = groups[groups.length - 1]
    if (last?.day === day) last.items.push(run)
    else groups.push({ day, items: [run] })
  }
  return groups
}

export function filterRuns<T extends Pick<AnalysisRun, 'question' | 'spec' | 'result' | 'status'>>(runs: readonly T[], filter: RunFilter, query: string, labels: Readonly<Record<string, string>>): T[] {
  const needle = query.trim().toLocaleLowerCase('ko-KR')
  return runs.filter(run => (filter === 'all' || runOutcome(run) === filter)
    && (!needle || runTitle(run, labels).toLocaleLowerCase('ko-KR').includes(needle)))
}

export function runFilterCounts(runs: readonly Pick<AnalysisRun, 'status' | 'result'>[]): Record<RunFilter, number> {
  const counts: Record<RunFilter, number> = { all: runs.length, matched: 0, empty: 0, error: 0 }
  for (const run of runs) { const outcome = runOutcome(run); if (outcome !== 'pending') counts[outcome]++ }
  return counts
}

/** 모바일 '마지막 검색' 카드 — 결과가 있는 가장 최근 실행, 병목 = 통과 수가 가장 적은 조건 */
export function lastSearch(runs: readonly AnalysisRun[], labels: Readonly<Record<string, string>>) {
  const run = runs.find(item => item.result)
  if (!run?.result) return null
  const funnel = run.result.condition_funnel
  const tightest = funnel?.conditions.length ? funnel.conditions.reduce((min, c) => c.passed < min.passed ? c : min) : null
  return {
    id: run.id, title: runTitle(run, labels), asOf: run.result.as_of,
    matched: run.result.counts.matched, evaluated: run.result.counts.evaluated,
    bottleneck: tightest && (funnel?.conditions.length ?? 0) > 1 ? { label: labels[tightest.strategy_id] ?? tightest.strategy_id, passed: tightest.passed } : null,
  }
}
