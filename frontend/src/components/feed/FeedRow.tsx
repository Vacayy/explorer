import { DetailLink as Link } from '@/components/shared/DetailNavigation'
import { SourceBadge } from '@/components/shared/SourceBadge'
import { EntityChip } from '@/components/shared/EntityChip'
import { highlightParts } from '@/lib/feed'
import { formatKstDateTime } from '@/utils/format'
import type { EntityTag, FeedDocument } from '@/types'

const focusLink = 'rounded-sm hover:underline focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-4'

// 목록 미리보기 — 마크다운 기호를 걷어 한 문단으로
function preview(text: string) {
  return text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/^[#>\-\s]+/gm, '').replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim()
}

function Marked({ text, q }: { text: string; q?: string }) {
  if (!q) return <>{text}</>
  return <>{highlightParts(text, q).map((p, i) => p.hit ? <mark key={i} className="rounded-sm bg-chart-warning/20 px-0.5 text-foreground">{p.text}</mark> : <span key={i}>{p.text}</span>)}</>
}

/**
 * 피드·문서 검색의 글 한 줄 (시안 Feed·Feed-Search) — 소스 칩 · 소스 이름 · 시각 · 안 읽음 점 / 제목 / 요약 / 종목·테마 칩.
 * 제목을 누르면 문서 보기, 소스 이름을 누르면 소스별 글.
 */
export function FeedRow({ doc, unread, q, onChip }: { doc: FeedDocument; unread?: boolean; q?: string; onChip: (tag: EntityTag) => void }) {
  const excerpt = preview(doc.summary || doc.content || '')
  const title = doc.title || excerpt.slice(0, 90) || '제목 없는 게시물'
  return (
    <article aria-label={title} className="flex flex-col gap-1.5 border-b py-4 first:pt-3 last:border-0" data-feed-row={doc.id}>
      <div className="flex min-w-0 items-center gap-2 text-xs text-ink-3">
        <SourceBadge sourceType={doc.source_type} />
        {doc.channel_kind && doc.channel_key
          ? <Link to={`/source?kind=${doc.channel_kind}&key=${encodeURIComponent(doc.channel_key)}`} className={`min-w-0 max-w-60 truncate font-medium text-ink-2 ${focusLink}`}>{doc.channel}</Link>
          : <span className="min-w-0 max-w-60 truncate font-medium text-ink-2">{doc.channel || '수집 자료'}</span>}
        <time className="shrink-0 font-mono tabular-nums" dateTime={doc.published_at} title={doc.published_at}>{formatKstDateTime(doc.published_at)}</time>
        {unread && <span className="ml-auto size-[7px] shrink-0 rounded-full bg-action" role="img" aria-label="안 읽음" />}
      </div>
      <h3 className="line-clamp-2 text-base leading-[1.45] font-semibold break-words text-pretty"><Link to={`/doc/${doc.id}`} className={focusLink}><Marked text={title} q={q} /></Link></h3>
      {excerpt && <p className="line-clamp-3 text-sm leading-[1.6] break-words text-ink-2 max-md:line-clamp-2"><Marked text={excerpt} q={q} /></p>}
      {doc.entities.length > 0 && <div className="flex flex-wrap gap-1.5">
        {doc.entities.slice(0, 4).map(tag => <EntityChip key={`${tag.entity_id}-${tag.link_type}`} tag={tag} onFilter={onChip} />)}
      </div>}
    </article>
  )
}
