import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readingEvidence } from '../src/components/company/scanEvidence.ts'

const entry = (id, status, value = null, reference = null) => ({ id, label: id, status, value, reference, date: '2026-09-22', category: '평균회귀', reason: null, within_days: 1 })

test('RSI 60 is neutral even when its sentence cites the failed oversold condition', () => {
  const conditions = [entry('rsi_oversold', 'fail', 60, 30), entry('rsi_overbought', 'fail', 60, 70)]
  const [evidence] = readingEvidence(['rsi_oversold'], conditions)
  assert.equal(evidence.label, 'RSI(14)')
  assert.equal(evidence.observation, 60)
  assert.equal(evidence.state, '중립')
  assert.deepEqual(evidence.conditions, conditions)
})

test('two failed MA conditions become one mixed observation without a misleading price', () => {
  const [evidence, extra] = readingEvidence(['sma_bullish_order', 'sma_bearish_order'], [entry('sma_bullish_order', 'fail', 200), entry('sma_bearish_order', 'fail', 200)])
  assert.equal(evidence.state, '혼조')
  assert.equal(evidence.observation, undefined)
  assert.equal(evidence.conditions.length, 2)
  assert.equal(extra, undefined)
})

test('missing and unavailable observations cannot be inferred to be neutral', () => {
  for (const conditions of [[], [entry('rsi_oversold', 'fail', 60)], [entry('rsi_oversold', 'unavailable'), entry('rsi_overbought', 'unavailable')]]) {
    assert.equal(readingEvidence(['rsi_oversold'], conditions)[0].state, '미평가')
  }
})

test('threshold states come from the actual verdict, not rounded display values', () => {
  const evaluate = (value, status) => readingEvidence(['rsi_oversold'], [entry('rsi_oversold', status, value, 30), entry('rsi_overbought', 'fail', value, 70)])[0]
  assert.equal(evaluate(30, 'pass').state, '과매도')
  assert.equal(evaluate(30.00000001, 'fail').state, '중립')
  assert.equal(evaluate(0, 'pass').observation, 0)
})

test('ordinary references always carry a verdict and price inputs are not passing signals', () => {
  const evidence = readingEvidence(['higher_lows', 'new_condition', 'price.close'], [entry('higher_lows', 'fail')], { 'price.close': '종가' })
  assert.deepEqual(evidence.map(item => item.state), ['불충족', '미평가', '관측 근거'])
})

const { technicalHighlights } = await import('../src/components/company/scanEvidence.ts')
test('three highlights preserve decimal observations and do not substitute a missing volume reading', () => {
  const input = [
    { group: '지표신호', text: '이동평균은 혼조입니다. 최근 교차 신호가 있습니다.', basis: [] },
    { group: '평균회귀', text: '20일선 대비 +7.5%. RSI 60로 중립입니다.', basis: [] },
    { group: '시세동향', text: '최근 고점 신호가 있습니다. 기준일 거래량은 20일 평균의 0.5배. 52주 고점 대비 -25.0%.', basis: [] },
  ]
  const result = technicalHighlights(input)
  assert.equal(result.length, 3)
  assert.equal(result[0].text, '이동평균은 혼조입니다.')
  assert.equal(result[1].text, input[1].text)
  assert.equal(result[2].text, '기준일 거래량은 20일 평균의 0.5배.')
  assert.match(technicalHighlights([])[2].text, /관측 문장이 없습니다/)
  assert.match(technicalHighlights([{ group: '시세동향', text: '최근 고점 신호가 있습니다.', basis: [] }])[2].text, /관측 문장이 없습니다/)
})
