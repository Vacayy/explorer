import type { ScanEntry, TechnicalScanResult } from '@/components/company/TechnicalScan'

export const SCAN_STATUS = { pass: '충족', fail: '불충족', unavailable: '미평가' } as const

const GROUPS = [
  { ids: ['rsi_oversold', 'rsi_overbought'], label: 'RSI(14)', states: ['과매도', '과매수'], otherwise: '중립' },
  { ids: ['sma_bullish_order', 'sma_bearish_order'], label: '이동평균 배열', states: ['정배열', '역배열'], otherwise: '혼조', hideValue: true },
  { ids: ['adx_strong_trend', 'adx_weak_trend'], label: 'ADX(14)', states: ['추세 강함', '추세 약함'], otherwise: '중간' },
  { ids: ['disparity_low', 'disparity_high'], label: '20일 이격도', states: ['하한 이하', '상한 이상'], otherwise: '설정 범위 안', unit: '%' },
  { ids: ['bollinger_below_lower', 'bollinger_above_upper'], label: '볼린저 밴드 위치', states: ['하단 아래', '상단 위'], otherwise: '밴드 안', hideValue: true },
] as const

export interface ReadingEvidence {
  id: string
  label: string
  observation?: number | null
  unit?: string
  state: string
  conditions: ScanEntry[]
}

/** Reuse server observations; no score or direction is inferred from pass counts. */
export function technicalHighlights(readings: TechnicalScanResult['readings'] = []) {
  const definitions = [
    { group: '지표신호', title: '이동평균의 방향', ids: ['sma_bullish_order', 'sma_bearish_order'] },
    { group: '평균회귀', title: '평균에서 떨어진 정도', ids: ['rsi_oversold', 'rsi_overbought'] },
    { group: '시세동향', title: '거래량의 동반 여부', ids: [] },
  ]
  return definitions.map(definition => {
    const reading = readings.find(reading => reading.group === definition.group)
    const sentences = reading?.text.split(/(?<=[.。])\s+/) ?? []
    const text = definition.group === '시세동향' ? sentences.find(text => text.includes('기준일 거래량'))
      : definition.group === '지표신호' ? sentences[0] : reading?.text
    return { ...definition, text: text || '이 항목의 관측 문장이 없습니다. 전체 계산 근거에서 자료 상태를 확인하세요.' }
  })
}

/** A basis is an input to a sentence, not necessarily a condition that passed. */
export function readingEvidence(ids: string[], entries: ScanEntry[], priceLabels: Record<string, string> = {}): ReadingEvidence[] {
  const byId = new Map(entries.map(entry => [entry.id, entry]))
  const seen = new Set<string>()
  return ids.flatMap(id => {
    const group = GROUPS.find(item => (item.ids as readonly string[]).includes(id))
    const key = group?.ids[0] ?? id
    if (seen.has(key)) return []
    seen.add(key)
    if (group) {
      const conditions = group.ids.flatMap(key => byId.has(key) ? [byId.get(key)!] : [])
      const complete = conditions.length === group.ids.length && conditions.every(entry => entry.status !== 'unavailable')
      const passing = group.ids.findIndex(key => byId.get(key)?.status === 'pass')
      return [{ id: key, label: group.label,
        observation: 'hideValue' in group ? undefined : conditions.find(entry => entry.value != null && entry.status !== 'unavailable')?.value,
        unit: 'unit' in group ? group.unit : undefined,
        state: passing >= 0 ? group.states[passing] : complete ? group.otherwise : '미평가', conditions }]
    }
    const entry = byId.get(id)
    return [{ id, label: entry?.label ?? priceLabels[id] ?? id,
      state: entry ? SCAN_STATUS[entry.status] : id in priceLabels ? '관측 근거' : '미평가',
      conditions: entry ? [entry] : [] }]
  })
}
