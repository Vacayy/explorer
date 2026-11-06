/**
 * 피드 대메뉴(/feed) 규칙 — 화면과 떼어 시험한다 (ia-redesign §4.5·§4.15·§4.26·§4.28).
 * URL이 상태의 단일 소스: view(피드|문서 검색), channel_type(종류 칩), channel(왼쪽 소스), reader_topic(주제 칩), reader_page, reading(원문|요약).
 */

/** 피드 리더 왼쪽 '내 피드'의 종류 칩(D-325, 옛 ChannelReader). Explorer 산출물(system)은 칩 없이 목록 맨 아래 묶음으로 들어온다 */
export const FEED_PLATFORMS = { telegram: '텔레그램', blog: '블로그', youtube: '유튜브', memo: '투자자 메모', system: 'Explorer' } as const
export type FeedPlatform = keyof typeof FEED_PLATFORMS | 'all'

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

/** 지금 종류 칩(channel_type). 모르는 값은 전체 */
export function feedPlatform(search: string): FeedPlatform {
  const raw = new URLSearchParams(search).get('channel_type') ?? 'all'
  return Object.hasOwn(FEED_PLATFORMS, raw) ? raw as FeedPlatform : 'all'
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
