/** 작은 SVG 선 차트 계산 — 시작 = 100 맞추기, polyline 좌표(0..w × pad..h-pad, lo·hi 공유). 섹터 카드·대표지수·Peer 미리보기가 쓴다 */
export const rebase = (vals: number[]) => vals.length && vals[0] ? vals.map(v => v / vals[0] * 100) : []

export function polyline(vals: number[], w: number, h: number, lo: number, hi: number, pad = 6): string {
  const n = vals.length
  return vals.map((v, i) => `${(n > 1 ? i / (n - 1) * w : 0).toFixed(1)},${(pad + (hi - v) / ((hi - lo) || 1) * (h - 2 * pad)).toFixed(1)}`).join(" ")
}

/** 값 v의 y 좌표 — polyline과 같은 눈금 */
export const yOf = (v: number, h: number, lo: number, hi: number, pad = 6) => pad + (hi - v) / ((hi - lo) || 1) * (h - 2 * pad)
