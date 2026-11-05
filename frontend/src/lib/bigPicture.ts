/**
 * Thesis › 지금 · 내러티브 상세 공용 순수 로직 (ia-redesign §4.18·§4.25·§4.33).
 */
import type { StrandStatus, WorldRebuildResult, WorldRebuildState } from '@/types'
import { dbAgeDays, formatKstDateTime } from '@/utils/format'

/** 낡음 규칙(§4.25) — 7일 넘으면 경고 띠, 14일 넘으면 흐리게 + '오래됨' */
export type StaleLevel = 'fresh' | 'stale' | 'old'
export function staleLevel(days: number | null | undefined): StaleLevel {
  if (days == null || !Number.isFinite(days)) return 'fresh'
  return days > 14 ? 'old' : days > 7 ? 'stale' : 'fresh'
}

/** DB 시각(UTC) → KST '11/4 13:00'. 비면 '-' */
export function kstShort(stamp: string | null | undefined): string {
  const s = formatKstDateTime(stamp)
  if (s === '-') return s
  const [md, hm] = s.split(' ')
  const [m, d] = md.split('-')
  return `${Number(m)}/${Number(d)} ${hm}`
}

/** DB 시각(UTC) → KST 'M/D' */
export const kstDay = (stamp: string | null | undefined) => kstShort(stamp).split(' ')[0]

/** 근거 범위 한 줄 — Partial이어도 0을 그대로 적는다(§4.25 5-state) */
export function inputsLabel(i: { narratives: number; mt_sessions: number; overnight_days: number }): string {
  return `내러티브 ${i.narratives}편 · Market Today ${i.mt_sessions}회차 · Overnight ${i.overnight_days}일`
}

/** 메가 서사 나이(일) — 줄기 카드 낡음 판정용 */
export const ageDays = (stamp: string | null | undefined) => {
  const d = dbAgeDays(stamp)
  return Number.isFinite(d) ? Math.floor(d) : null
}

/**
 * 내러티브 본문(마크다운)에서 '3줄 요약' 절을 떼어 낸다 — 상세 머리 아래 요약 상자(§4.18).
 * 절 제목(#·## 등) 다음 목록 줄(-, *, 1.)을 문장으로, 나머지는 본문으로 돌려준다. 절이 없으면 요약 [].
 */
export function splitSummary(md: string): { summary: string[]; body: string } {
  const lines = md.split('\n')
  const start = lines.findIndex((l) => /^#{1,4}\s*3줄\s*요약/.test(l.trim()))
  if (start < 0) return { summary: [], body: md }
  let end = start + 1
  const summary: string[] = []
  for (; end < lines.length; end++) {
    const t = lines[end].trim()
    if (/^#{1,4}\s/.test(t)) break
    const item = t.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/)
    if (item) summary.push(item[1].trim())
    else if (t) summary.push(t)
  }
  const body = [...lines.slice(0, start), ...lines.slice(end)].join('\n').replace(/^\s+/, '')
  return { summary, body }
}

/** 줄기 상태 → 화면 말 (§4.25) */
export const STRAND_STATUS_LABEL: Record<StrandStatus, string> = {
  strengthening: '강해짐', mixed: '엇갈림', weakening: '약해짐', new: '새로',
}

/** '다시 만들기'를 누를 수 없을 때 ⓘ 툴팁 문장 — 쿨다운 6시간 · 주간 한도 · 엔진 꺼짐 */
export function rebuildBlockedReason(s: WorldRebuildState): string | null {
  if (s.available) return null
  if (s.reason === 'cooldown') return `${kstShort(s.retry_at)} 이후 다시 만들 수 있어요 (6시간 간격)`
  if (s.reason === 'budget') return `이번 주 생성 한도를 다 썼어요 · ${kstDay(s.retry_at)}부터 다시`
  return 'AI 엔진이 꺼져 있어 지금은 만들 수 없어요'
}

/** 다시 만들기 결과 → 알림 문장. ok만 성공, 나머지는 이유 */
export function rebuildResultMessage(r: WorldRebuildResult): { ok: boolean; text: string } {
  switch (r.status) {
    case 'ok': return { ok: true, text: `이번 주 큰 그림을 다시 만들었습니다 · 줄기 ${r.strands ?? 0}개` }
    case 'skipped': return { ok: true, text: '지난 생성 뒤 근거가 그대로라 다시 만들지 않았습니다' }
    case 'cooldown': return { ok: false, text: `${kstShort(r.retry_at)} 이후 다시 만들 수 있습니다` }
    case 'budget': return { ok: false, text: '이번 주 생성 한도를 다 썼습니다' }
    case 'empty': return { ok: false, text: '최근 7일 새 내러티브가 없어 만들지 않았습니다' }
    case 'unavailable': return { ok: false, text: 'AI 엔진이 꺼져 있어 만들지 못했습니다' }
    case 'off': return { ok: false, text: '관리자 설정에서 꺼져 있습니다' }
    default: return { ok: false, text: '큰 그림을 다시 만들지 못했습니다 · 이전 것을 그대로 둡니다' }
  }
}
