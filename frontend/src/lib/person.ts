/**
 * 인물 1단계 공용 (ia-redesign §4.23) — id 주소·역할 칩·전제 판정 배지.
 */
import type { PersonRole, PersonRoleName, PremiseStatus } from '@/types'

/** 인물 상세 주소 — id 기반(§10.6) */
export const personPath = (id: number) => `/person/${id}`

export const ROLE_LABEL: Record<PersonRoleName, string> = { policy: '정책', executive: '경영자', guru: '구루' }
export const ROLE_ORDER: PersonRoleName[] = ['policy', 'executive', 'guru']

/** 역할 칩 옆 소속 한 줄 — '연준 · 의장', 'NVIDIA · CEO' */
export function roleOrg(r: PersonRole | null): string | null {
  if (!r) return null
  const parts = [r.org, r.title].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

/** 전제 판정 배지(매크로 › 구루 전제 원장과 같은 값) */
export const PREMISE_STATUS: Record<PremiseStatus | 'none', { label: string; variant: 'fact' | 'up' | 'warn' | 'neutral' }> = {
  supports: { label: '지지', variant: 'fact' },
  challenges: { label: '반증 쪽', variant: 'up' },
  mixed: { label: '엇갈림', variant: 'warn' },
  untestable: { label: '반증 불가', variant: 'neutral' },
  nodata: { label: '데이터 없음', variant: 'neutral' },
  none: { label: '판정 불가', variant: 'neutral' },
}

/** 판정 분포 한 줄 — '지지 1 · 반증 불가 1 · 데이터 없음 2' (0은 뺀다) */
export function verdictSummary(statuses: (PremiseStatus | null)[]): string {
  const counts = new Map<string, number>()
  for (const s of statuses) { const l = PREMISE_STATUS[s ?? 'none'].label; counts.set(l, (counts.get(l) ?? 0) + 1) }
  return [...counts].map(([l, n]) => `${l} ${n}`).join(' · ')
}

/** URL ?role= → 역할 필터(없거나 모르는 값이면 전체) */
export function roleFilter(v: string | null): PersonRoleName | 'all' {
  return v === 'policy' || v === 'executive' || v === 'guru' ? v : 'all'
}
