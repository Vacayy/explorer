/** /home의 보기 — 옛 피드 주소(home_view=feed)인가. 피드는 /feed로 옮겼다(ia-redesign §10.6) */
export function getHomeMode(search: string): 'market' | 'feed' {
  return new URLSearchParams(search).get('home_view') === 'feed' ? 'feed' : 'market'
}
