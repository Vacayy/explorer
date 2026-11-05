import { describe, expect, it } from 'vitest'
import {
  judgmentView, proxiesUrl, ratingLabel, ratingTone, relabelRatings, reportSectionNames, scenarioSide, sinceChange, splitReportBody, splitSynthesis,
} from '@/lib/judgment'

describe('내 판단 보기 전환', () => {
  it('주소로 보기를 정한다 — 지표 보드는 /questions?view=proxies', () => {
    expect(judgmentView('/questions', '')).toBe('questions')
    expect(judgmentView('/question/2', '')).toBe('questions')
    expect(judgmentView('/thesis', '?audit=2')).toBe('thesis')
    expect(judgmentView('/report', '?topic=반도체')).toBe('report')
    expect(judgmentView('/questions', '?view=proxies&board=1')).toBe('proxies')
    expect(judgmentView('/proxy-boards', '')).toBe('proxies')
    expect(judgmentView('/question/2', '?view=proxies')).toBe('questions')
  })
  it('옛 지표 주소는 /questions?view=proxies로, 다른 쿼리는 그대로', () => {
    expect(proxiesUrl('?board=3')).toBe('/questions?view=proxies&board=3')
    expect(proxiesUrl('?view=proxies')).toBe('/questions?view=proxies')
    expect(proxiesUrl('')).toBe('/questions?view=proxies')
  })
})

describe('리포트 레이팅 말 (11-04 매매 권유 낮춤)', () => {
  it('옛 영문 레이팅을 새 말로, Hold·새 말은 그대로', () => {
    expect(['Strong Buy', 'Buy', 'Hold', 'Sell', '상방 우위', null].map(ratingLabel))
      .toEqual(['상방 우위(비대칭 큼)', '상방 우위', 'Hold', '하방 우위', '상방 우위', null])
    expect(['Strong Buy', '상방 우위', 'Hold', 'Sell'].map(ratingTone)).toEqual(['up-strong', 'up', 'neutral', 'down'])
  })
  it('본문 속 영문 레이팅만 바꾸고 Buy-side·Sell-off는 둔다', () => {
    expect(relabelRatings('**SK하이닉스(000660) — Strong Buy · 상방 +55%**, 삼성 Buy, 한미 Hold, 이수 Sell. Buy-side·Sell-off'))
      .toBe('**SK하이닉스(000660) — 상방 우위(비대칭 큼) · 상방 +55%**, 삼성 상방 우위, 한미 Hold, 이수 하방 우위. Buy-side·Sell-off')
  })
})

describe('리포트 작성 이후 변화', () => {
  const s = [{ date: '2026-07-24', value: 100 }, { date: '2026-07-27', value: 120 }, { date: '2026-07-28', value: 130 }, { date: '2026-11-03', value: 90 }]
  it('작성일(그날 포함 이전 마지막 값) → 최신', () => {
    expect(sinceChange(s, '2026-07-27 14:50:23')).toEqual({ fromDate: '2026-07-27', from: 120, toDate: '2026-11-03', to: 90, pct: -25 })
    expect(sinceChange(s, '2026-07-26')?.from).toBe(100)              // 주말 작성 → 직전 거래일
  })
  it('작성 이전 값이 없거나 작성 뒤 값이 없으면 null', () => {
    expect(sinceChange(s, '2026-07-01')).toBeNull()
    expect(sinceChange(s, '2026-11-03')).toBeNull()
    expect(sinceChange([], '2026-07-27')).toBeNull()
  })
})

describe('접을 본문', () => {
  it('리포트 — 결론·핵심 질문·투자 포인트 요약 뒤의 섹션을 접는다', () => {
    const md = '## 결론\n\nA\n\n## 핵심 질문\n\nB\n\n## 투자 포인트 요약\n\nC\n\n## 산업 분석\n\nD\n\n## 기업 분석\n\nE'
    const { head, rest } = splitReportBody(md)
    expect(head).toBe('## 결론\n\nA\n\n## 핵심 질문\n\nB\n\n## 투자 포인트 요약\n\nC')
    expect(reportSectionNames(rest)).toEqual(['산업 분석', '기업 분석'])
    expect(splitReportBody('본문만')).toEqual({ head: '본문만', rest: '' })
  })
  it('질문 종합 — 아직 미판정부터 접는다', () => {
    const md = '## 결산: X\n\n요지\n\n### 확인된 것\n\n- a\n\n### 아직 미판정\n\n- b\n\n### 딛고 선 전제와 흔들릴 조건\n\n- c'
    const { main, folded } = splitSynthesis(md)
    expect(main).toBe('## 결산: X\n\n요지\n\n### 확인된 것\n\n- a')
    expect(folded.startsWith('### 아직 미판정')).toBe(true)
    expect(splitSynthesis('요지만').folded).toBe('')
  })
  it('시나리오 수혜·피해 → 유리·불리', () => {
    expect(['수혜', '피해', '유리', '불리', undefined].map(scenarioSide)).toEqual(['유리', '불리', '유리', '불리', null])
  })
})
