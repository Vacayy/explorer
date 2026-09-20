import type { StrategyCheck } from './types'

export const EXCLUSION_LABELS: Record<string, string> = {
  insufficient_history: '분석에 필요한 과거 시세 부족',
  invalid_ohlcv: '시가·고가·저가·종가 또는 거래량 오류',
  missing_as_of: '기준일 시세 없음',
  missing_observed_sessions: '관측 거래일의 시세 누락',
  duplicate_dates: '같은 거래일의 시세 중복',
  missing_market_cap: '기준일 시가총액 없음',
  unknown_market: '소속 시장 미확인',
  missing_intraday: '10분봉 시세 없음',
  missing_trading_value: '실제 거래대금 자료 없음',
  missing_shares: '기준일 상장주식 수 없음',
  zero_reference_volume: '비교 구간의 거래량이 0이라 비율 계산 불가',
  zero_price_range: '비교 구간의 고가와 저가가 같아 지표 계산 불가',
  invalid_numeric_result: '지표 계산 값이 유효한 범위를 벗어남',
  invalid_history: '가격 이력 형식 또는 크기 오류',
  invalid_dates: '시세 날짜의 순서 또는 형식 오류',
  invalid_ohlc: '고가·저가·종가 범위 오류',
  invalid_shares: '상장주식 수가 유효하지 않음',
  missing_intraday_bars: '10분봉 구간 누락',
  no_prior_breakout: '선행 신고가 돌파 없음',
  insufficient_pivots: '확정된 스윙 고점·저점 부족',
  no_trend_pivots: '스윙 점이 한 방향으로 정렬되지 않음',
  no_retest: '돌파 뒤 되돌림 구간 없음',
  line_out_of_range: '추세선 연장값이 유효 범위 밖',
}

export function strategyCheck(value: unknown): StrategyCheck {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as StrategyCheck : {}
}

export function evidenceValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString('ko-KR', { maximumFractionDigits: 4 }) : '—'
  if (typeof value === 'string') return value || '—'
  if (typeof value === 'boolean') return value ? '예' : '아니요'
  return '—'
}

export function checkValue(value: unknown): string {
  if (value === true || value === 'pass' || value === 'passed') return '통과'
  if (value === false || value === 'fail' || value === 'failed') return '탈락'
  if (value === 'unavailable') return '판단 불가'
  if (value == null || value === 'unknown' || value === 'unverified') return '미검증'
  if (value === 'not_requested') return '요청 조건 아님'
  if (typeof value === 'object') {
    const check = value as StrategyCheck & { passed?: unknown }
    const label = checkValue(check.status ?? check.passed)
    return check.reason ? `${label} · ${EXCLUSION_LABELS[check.reason] ?? check.reason}` : label
  }
  return String(value)
}
