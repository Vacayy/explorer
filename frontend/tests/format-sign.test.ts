import { describe, expect, it } from 'vitest'
import { formatBp, formatKrw, formatPercent, formatPp, formatSigma } from '@/utils/format'

// 부호 문자 — 음수는 −(U+2212), 표시 자릿수로 0이 되면 부호 없음 (D-320, docs/policies/number-formatting.md)
describe('signed formatters', () => {
  it('uses U+2212 for negatives', () => {
    expect(formatPercent(-0.51)).toBe('−0.5%')
    expect(formatPp(-3.2, 1)).toBe('−3.2%p')
    expect(formatSigma(-1.4)).toBe('−1.4σ')
    expect(formatBp(-6, true)).toBe('−6')
    expect(formatKrw(-150_000_000_000)).toBe('−1,500억')
  })
  it('keeps + for positives and drops the sign at displayed zero', () => {
    expect(formatPercent(1.53)).toBe('+1.5%')
    expect(formatPercent(-0.04)).toBe('0.0%')
    expect(formatBp(71, true)).toBe('+71')
    expect(formatPercent(null)).toBe('-')
  })
})
