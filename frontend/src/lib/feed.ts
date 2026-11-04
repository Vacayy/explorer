/**
 * 피드 대메뉴(/feed) 규칙 — 화면과 떼어 시험한다 (ia-redesign §4.5·§4.15·§4.26·§4.28).
 * URL이 상태의 단일 소스: view(피드|문서 검색), channel_type(소스 칩), channel(왼쪽 소스), reader_topic(부상 종목).
 */
import type { TimelineChannel, TimelineItem } from '@/types'

/** 소스 칩 — timeline이면 안 읽음을 아는 타임라인(/feed/timeline), 아니면 문서 코퍼스(/api/spine/feed?source=)에서 최신순.
 *  블로그는 타임라인에서 뉴스 RSS와 섞이므로 문서 분류를 따른다. 스크랩은 미검증이라 '전체'에 섞지 않고 구분선 뒤에 둔다. */
export const FEED_CHIPS = [
  { key: 'all', label: '전체', timeline: true },
  { key: 'telegram', label: '텔레그램', timeline: true },
  { key: 'blog', label: '블로그', timeline: false },
  { key: 'youtube', label: '유튜브', timeline: true },
  { key: 'news', label: '뉴스', timeline: false },
  { key: 'article', label: '아티클', timeline: false },
  { key: 'transcript', label: '컨콜', timeline: false },
  { key: 'people', label: '인물', timeline: false },
  { key: 'canon', label: '역사', timeline: false },
  { key: 'memo', label: '메모', timeline: true },
  { key: 'scrap', label: '스크랩 · 미검증', timeline: false },
] as const
export type FeedChipKey = (typeof FEED_CHIPS)[number]['key'] | 'system'

/** 문서 검색의 소스 칩(시안 Feed-Search) */
export const SEARCH_SOURCES = [
  { key: 'all', label: '전체' }, { key: 'telegram', label: '텔레그램' }, { key: 'blog', label: '블로그' }, { key: 'youtube', label: '유튜브' },
  { key: 'news', label: '뉴스' }, { key: 'article', label: '아티클' }, { key: 'transcript', label: '컨콜' },
] as const

/** 문서 검색 보기인가 — 옛 /feed?source=·?q= 주소도 문서 검색으로 연다 */
export function isSearchView(search: string): boolean {
  const p = new URLSearchParams(search)
  return p.get('view') === 'documents' || ['q', 'source', 'stock', 'industry', 'topic', 'page'].some(k => p.has(k))
}

/** 현재 소스 칩. 왼쪽에서 소스를 고르면 칩은 그 소스 종류를 따른다. Explorer 산출물(system)은 칩 없이 맨 아래 한 줄로 들어온다 */
export function feedChip(search: string): FeedChipKey {
  const p = new URLSearchParams(search)
  const raw = p.get('channel_type') ?? 'all'
  if (raw === 'system') return 'system'
  return FEED_CHIPS.some(c => c.key === raw) ? raw as FeedChipKey : 'all'
}

export function usesTimeline(chip: FeedChipKey, channel: string): boolean {
  return !!channel || chip === 'system' || FEED_CHIPS.some(c => c.key === chip && c.timeline)
}

/** 게시물 → 소스 id(`telegram:채널`·`blog:url`·`youtube:채널`) — /feed/channels의 id와 같은 꼴 */
export function itemChannelId(item: TimelineItem): string | null {
  const d = item.document
  return d?.channel_kind && d.channel_key ? `${d.channel_kind}:${d.channel_key}` : null
}

/**
 * 안 읽음 점 — 소스별 안 읽음 수(n)만 알므로, 최신순 목록에서 소스마다 앞의 n개를 안 읽음으로 본다.
 * '더 불러오기'로 이어 붙인 목록 전체를 한 번에 넘긴다.
 */
export function unreadIds(items: TimelineItem[], channels: TimelineChannel[]): Set<string> {
  const left = new Map(channels.map(c => [c.id, c.unread]))
  const out = new Set<string>()
  for (const item of items) {
    const id = itemChannelId(item)
    const n = id ? left.get(id) ?? 0 : 0
    if (id && n > 0) { out.add(item.id); left.set(id, n - 1) }
  }
  return out
}

/** 새 글이 끊긴 소스(7일 이상) — 흐리게만 표시하고 정리는 관리자 › 소스에서 한다(§4.28 부분) */
export function isQuiet(latestAt: string | null, now: Date = new Date(), days = 7): boolean {
  if (!latestAt) return true
  return now.getTime() - new Date(latestAt).getTime() > days * 86_400_000
}

/** 검색어 강조 — 공백으로 나눈 단어를 대소문자 없이 찾아 [text, matched] 조각으로 */
export function highlightParts(text: string, q: string): { text: string; hit: boolean }[] {
  const words = q.trim().split(/\s+/).filter(w => w.length > 0).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!text || words.length === 0) return [{ text, hit: false }]
  // 잡는 괄호로 나누면 홀수 번째 조각이 일치한 부분이다
  return text.split(new RegExp(`(${words.join('|')})`, 'gi')).map((s, i) => ({ text: s, hit: i % 2 === 1 })).filter(p => p.text !== '')
}
