import { AddToStudy } from '@/components/study/AddToStudy'
import { StudyButton } from '@/components/study/StudyButton'
import { DocumentBody } from '@/components/doc/DocumentBody'
import { useState, type ReactNode } from 'react'
import { DetailLink as Link } from '@/components/shared/DetailNavigation'
import { ArrowUpRight, ChevronDown, FileText, Sparkles } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Markdown } from '@/components/shared/Markdown'
import { BoundedArea } from '@/components/shared/Bounded'
import { SourceBadge } from '@/components/shared/SourceBadge'
import { EntityChip } from '@/components/shared/EntityChip'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import type { EntityTag, FeedDocument, TimelineItem } from '@/types'

type PostVariant = 'card' | 'row'
function PostSurface({ variant, children }: { variant: PostVariant; children: ReactNode }) {
  if (variant === 'row') return <div className="space-y-3">{children}</div>
  return <Card className="gap-0 py-0"><CardContent className="space-y-3 p-3 sm:p-3">{children}</CardContent></Card>
}

const focusLink = 'rounded-sm hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-4'
const labels = { source: '소스', company: '기업 요약', person: '인물 요약', transcript: '컨콜', trade: '수출입', narrative: '내러티브', report: '리포트', scenario: '파급 분석' }

// Preview only: preserve full stored Markdown inside the expanded body / original page.
function preview(text: string) {
  return text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/^[#>\-\s]+/gm, '').replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim()
}

/** 피드 리더의 글 카드(D-325, 옛 ChannelReader) — 분류 · 소스 · 시각 / 제목 / 요약(기본) · '원문 보기'로 원문 펼침 / 태그 · 스터디로 읽기 · 스터디에 추가 · 자료 상세 · 원문 사이트.
 *  요약이 없으면 원문을 바로 보인다. 펼친 원문은 높이 상한 안에서 스크롤한다(§4.34). */
export function DocumentCard({ doc, onChipFilter, timeLabel = '게시' }: {
  doc: FeedDocument; onChipFilter: (tag: EntityTag) => void; timeLabel?: string
}) {
  const excerpt = preview(doc.summary || doc.content || '')
  const hasSummary = !!doc.summary?.trim()
  const hasOriginal = !!doc.content?.trim() || doc.images.length > 0
  const [showOriginal, setShowOriginal] = useState(false)
  return (
    <article aria-label={doc.title || '소스 게시물'} className="feed-post-row">
      <div className="space-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
          <SourceBadge sourceType={doc.source_type} />
          {doc.channel_kind && doc.channel_key ? (
            <Link to={`/source?kind=${doc.channel_kind}&key=${encodeURIComponent(doc.channel_key)}`}
              className={`min-w-0 max-w-[60%] truncate font-medium text-ink-2 ${focusLink}`}>{doc.channel}</Link>
          ) : <span className="min-w-0 truncate font-medium text-ink-2">{doc.channel || '수집 자료'}</span>}
          <time className="ml-auto shrink-0 text-caption" dateTime={doc.published_at} title={doc.published_at}>
            {formatRelativeTime(doc.published_at)} {timeLabel}
          </time>
        </div>
        <h3 className="text-card-title font-semibold text-pretty break-words">
          <Link to={`/doc/${doc.id}`} className={focusLink}>{doc.title || excerpt.slice(0, 90) || '제목 없는 게시물'}</Link>
        </h3>
        <DocumentBody doc={doc} reading={hasSummary ? 'summary' : 'original'} mediaSize="preview" />
        {hasSummary && hasOriginal && <>
          <Button variant="ghost" size="sm" className="-ml-2 text-caption text-ink-2" aria-expanded={showOriginal} onClick={() => setShowOriginal(v => !v)}>
            {showOriginal ? '원문 접기' : '원문 보기'}<ChevronDown aria-hidden="true" className={`size-3 transition-transform ${showOriginal ? 'rotate-180' : ''}`} />
          </Button>
          {showOriginal && <BoundedArea size="md" className="rounded-lg border border-line bg-surface-2/50" viewportClassName="p-3">
            <DocumentBody doc={doc} reading="original" mediaSize="preview" />
          </BoundedArea>}
        </>}
        <div className="flex flex-wrap items-center gap-2">
          {doc.entities.slice(0, 4).map(tag => <EntityChip key={`${tag.entity_id}-${tag.link_type}`} tag={tag} onFilter={onChipFilter} />)}
          <StudyButton documentId={doc.id} /><AddToStudy documentId={doc.id} />
          <Button asChild variant="ghost" size="sm" className="ml-auto"><Link to={`/doc/${doc.id}`}>자료 상세<ArrowUpRight aria-hidden="true" /></Link></Button>
          {/^https?:\/\//i.test(doc.url) && <Button asChild variant="outline" size="sm"><a href={doc.url} target="_blank" rel="noreferrer"><span>원문<span className="max-md:hidden"> 사이트</span></span><ArrowUpRight aria-hidden="true" /></a></Button>}
        </div>
      </div>
    </article>
  )
}

export function SystemPost({ item, variant = 'card', presentation = 'preview' }: { item: TimelineItem; variant?: PostVariant; presentation?: 'preview' | 'reading' }) {
  const [open, setOpen] = useState(false)
  return (
    <article aria-label={item.title} className={variant === 'row' ? 'feed-post-row' : undefined}>
      <PostSurface variant={variant}>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 font-semibold"><Sparkles aria-hidden="true" className="size-3.5 text-hypothesis" />Explorer</span>
            <Badge variant="outline" className="text-caption font-normal">{labels[item.kind]}</Badge>
            <time className="ml-auto text-caption text-muted-foreground" dateTime={item.occurred_at} title={item.occurred_at}>{formatRelativeTime(item.occurred_at)} {item.time_label}</time>
          </div>
          <h3 className="break-words text-card-title font-semibold text-pretty"><Link to={item.to} className={focusLink}>{item.title}</Link></h3>
          <Collapsible open={presentation === 'reading' || open} onOpenChange={setOpen}>
            {presentation === 'preview' && !open && <p className="line-clamp-3 break-words text-sm leading-relaxed text-muted-foreground">{preview(item.body)}</p>}
            <CollapsibleContent>
              <div tabIndex={0} aria-label="업데이트 내용" className="break-words text-reading"><Markdown className="text-[length:var(--text-reading)] leading-[var(--text-reading--line-height)] [&_h2]:text-[length:var(--text-section)] [&_h3]:text-[length:var(--text-card-title)] [overflow-wrap:anywhere] [&_pre]:overflow-x-auto">{item.body}</Markdown></div>
            </CollapsibleContent>
            <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">
              <span className={item.ai_generated ? 'text-hypothesis' : 'text-fact'}>{item.ai_generated ? 'AI 요약 · 해석' : '수집 업데이트'}</span>
              {item.evidence_count != null && <span>· 자료 {formatNumber(item.evidence_count)}건</span>}
              {item.period && <span>· {item.period}</span>}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              {presentation === 'preview' && <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="text-caption text-muted-foreground">{open ? '접기' : item.ai_generated ? '요약 펼치기' : '내용 펼치기'}<ChevronDown aria-hidden="true" className={`size-3 ${open ? 'rotate-180' : ''}`} /></Button></CollapsibleTrigger>}
              <Link to={item.to} className={`ml-auto inline-flex items-center gap-1 text-xs ${focusLink}`}>상세 보기<ArrowUpRight aria-hidden="true" className="size-3" /></Link>
            </div>
          </Collapsible>
          {item.links.length > 0 && <div className="flex flex-wrap gap-x-3 gap-y-2 border-t pt-2">{item.links.map(link => <Link key={link.to} to={link.to} className={`inline-flex items-center gap-1 text-caption text-muted-foreground ${focusLink}`}><FileText aria-hidden="true" className="size-3" />{link.label}</Link>)}</div>}
      </PostSurface>
    </article>
  )
}
