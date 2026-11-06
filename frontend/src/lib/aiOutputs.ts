import type { AiActivityItem, TimelineItem } from '@/types'

/** 'AI가 최근 만든 것' 한 줄 — 종류 라벨 · 제목 · 시각 · 이동 주소 */
export interface AiOutput { id: string; kind: string; title: string; occurred_at: string; to: string }

/** 두 원천이 같은 산출물을 가리키는지 맞출 종류 — 옛 원천의 digest=기업 요약, mega=내러티브 표 */
const SAME_KIND: Record<string, string> = { digest: 'company', mega: 'narrative' }

/** 'YYYY-MM-DD HH:MM:SS'(UTC, 시간대 없음)와 ISO 모두 epoch 초로 */
function epochSec(at: string): number {
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : `${at.replace(' ', 'T')}Z`
  return Math.floor(new Date(iso).getTime() / 1000)
}

function activityLink(a: AiActivityItem): string {
  if (a.type === 'youtube_digest' && a.doc_id) return `/doc/${a.doc_id}?reading=digest`
  if (a.type === 'report') return `/report?topic=${encodeURIComponent(a.topic)}`
  if (a.type === 'digest' && a.code) return `/analyze/${a.code}/summary`
  if (a.type === 'scenario' && a.question_id) return `/question/${a.question_id}`
  return `/narrative?topic=${encodeURIComponent(a.topic)}`
}

/**
 * 타임라인(scope=system) + 옛 ai-activity 원천을 합친다. 같은 산출물(종류·주제·생성 시각 초)이 두 번 오면 타임라인 쪽을 남긴다
 * (링크·제목이 피드와 같다). 최신순.
 */
export function mergeAiOutputs(timeline: TimelineItem[], activity: AiActivityItem[]): AiOutput[] {
  const seen = new Set<string>()
  const out: AiOutput[] = []
  for (const t of timeline) {
    seen.add(`${t.kind}|${t.subject}|${epochSec(t.occurred_at)}`)
    out.push({ id: t.id, kind: t.kind, title: t.title, occurred_at: t.occurred_at, to: t.to })
  }
  for (const a of activity) {
    const key = `${SAME_KIND[a.type] ?? a.type}|${a.topic}|${epochSec(a.created_at)}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ id: `activity:${key}`, kind: a.type, title: a.title, occurred_at: new Date(epochSec(a.created_at) * 1000).toISOString(), to: activityLink(a) })
  }
  return out.sort((x, y) => epochSec(y.occurred_at) - epochSec(x.occurred_at))
}
