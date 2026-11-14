/**
 * 공급 지도의 금액 규모(docs/specs/value-chain.md §14) — 칸 규모 → 중력 원 지름(로그), 선별 추정 증가액 → 선 굵기(제곱근).
 * 선 굵기는 실제 거래액이 아니라 공급 칸 증가액을 사는 칸 규모 비례로 나눈 추정이다.
 */

export const MAG_HINT = "선 굵기는 실제 거래액이 아닙니다 — 공급 칸의 전년 대비 증가액을, 그 칸이 파는 칸들에 사는 칸 규모 비례로 나눈 추정입니다."

/** 로그 스케일 지름(px) — 회사 전체 매출과 수출 품목 하나는 수백 배 차이라 선형이면 작은 칸이 사라진다 */
export function gravity(level: number | null | undefined, min: number, max: number, lo = 8, hi = 30): number | null {
  if (!level || level <= 0 || !(max > min)) return level ? (lo + hi) / 2 : null
  const t = (Math.log(level) - Math.log(min)) / (Math.log(max) - Math.log(min))
  return lo + Math.max(0, Math.min(1, t)) * (hi - lo)
}

/** 제곱근 스케일 선 굵기(px) — 증가액이 0 이하이거나 모르면 가는 기본선 */
export function streamWidth(flow: number | null | undefined, max: number, lo = 1, hi = 14): number {
  if (!flow || flow <= 0 || max <= 0) return lo
  return lo + Math.sqrt(flow / max) * (hi - lo)
}
