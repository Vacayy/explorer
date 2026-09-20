export function safeEvidenceUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null
  } catch { return null }
}

export function evidenceText(source: unknown): string {
  if (typeof source === 'string') return source
  if (!source || typeof source !== 'object') return '출처 미확인'
  const value = source as Record<string, unknown>
  return [value.label, value.name, value.type, value.source_type, value.provider].filter(item => typeof item === 'string').join(' · ') || '저장된 기업 자료'
}

export function researchStatus(status: string): string {
  return ({ queued: '조사 대기', running: '조사 중', completed: '완료', partial: '일부 확인', failed: '실행 오류', error: '자료 조회 실패', cancelled: '취소됨', interrupted: '실행 중단', available: '자료 있음', ready: '자료 있음', empty: '자료 없음', missing: '자료 없음', unavailable: '자료 미확보', unknown: '미확인' } as Record<string, string>)[status] ?? status
}

export function claimKind(kind: string): string {
  return ({ fact: '확인한 사실·계산', source_claim: '자료 작성자의 주장', inference: '모델의 추론', unknown: '아직 모르는 것' } as Record<string, string>)[kind] ?? '미분류'
}

export function timePrecision(value: string): string {
  return ({ day: '날짜까지 확인', date: '날짜까지 확인', time: '시각까지 확인', timestamp: '시각까지 확인', datetime: '시각까지 확인', exact: '시각까지 확인', month: '월 단위', quarter: '분기 단위', unknown: '공개 시점 미확인' } as Record<string, string>)[value] ?? '자료의 공개 시점 확인 필요'
}

/** Translate model field labels only; source excerpts remain verbatim. */
export function researchProse(text: string): string {
  return text.replace(/\((?:earnings|call|industry|market|trade)\)/g, '')
    .replace(/\bsource_claim\b/g, '자료 작성자의 주장')
    .replace(/\buser_judgment\b/g, '사용자 판단 기록')
    .replace(/discovery 근거/g, '발견 당시 계산 근거')
    .replace(/레인/g, '자료 부문')
}

export function discoveryPriceAdjustment(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined
  const candidate = value as { checks?: { price_adjustment?: { source_status?: string } } }
  return candidate.checks?.price_adjustment?.source_status
}

export function preparationStatus(status: string): string {
  return ({ pending: '확인 대기', checking: '보유 자료 확인 중', collecting: '수집 중', available: '보유 자료 확인', collected: '수집 완료', unpublished: '자료원에서 미제공', unsupported: '자동 수집하지 않음', failed: '수집 실패 · 재시도 가능' } as Record<string, string>)[status] ?? '확인 필요'
}

export function researchPhase(phase: string | undefined, status: string): string {
  if (status === 'queued') return '기업 조사를 준비하고 있습니다'
  return ({ preparing: '필요한 기업 자료를 준비하고 있습니다', reading: '확보한 자료를 읽고 있습니다', analyzing: '근거와 반대 근거를 연결하고 있습니다', complete: '조사를 마쳤습니다' } as Record<string, string>)[phase ?? ''] ?? '자료를 읽고 근거를 연결하고 있습니다'
}

export function researchDate(value: string): string {
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value.replace(' ', 'T')}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
