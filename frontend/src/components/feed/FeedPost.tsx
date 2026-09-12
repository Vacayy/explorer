import { AddToStudy } from "@/components/study/AddToStudy"
import { StudyButton } from "@/components/study/StudyButton"
import { DocumentBody } from "@/components/doc/DocumentBody"
import { useState, type ReactNode } from 'react'
import { DetailLink as Link } from '@/components/shared/DetailNavigation'
import { ArrowUpRight, ChevronDown, FileText, Sparkles } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Markdown } from '@/components/shared/Markdown'
import { SourceBadge } from '@/components/shared/SourceBadge'
import { EntityChip } from '@/components/shared/EntityChip'
import { API_BASE } from '@/api/client'
import { formatNumber, formatRelativeTime } from '@/utils/format'
import type { EntityTag, FeedDocument, TimelineItem } from '@/types'

type PostVariant = 'card' | 'row'
function PostSurface({ variant, children }: { variant: PostVariant; children: ReactNode }) {
  if (variant === 'row') return <div className="space-y-3">{children}</div>
  return <Card className="gap-0 py-0"><CardContent className="space-y-3 p-4 sm:p-5">{children}</CardContent></Card>
}

const focusLink = 'rounded-sm hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-4'
const labels = { source: '소스', company: '기업 요약', person: '인물 요약', transcript: '컨콜', trade: '수출입' }

// Preview only: preserve full stored Markdown inside the expanded body / original page.
function preview(text: string) {
  return text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/^[#>\-\s]+/gm, '').replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim()
}

export function DocumentCard({ doc, onChipFilter, compact = false, timeLabel = '게시', variant = 'card', reading }: {
  doc: FeedDocument; onChipFilter: (tag: EntityTag) => void; compact?: boolean; timeLabel?: string; variant?: PostVariant; reading?: 'original' | 'summary'
}) {
  const [open, setOpen] = useState(false)
  const excerpt = preview(doc.summary || doc.content || '')
  const tags = doc.entities.slice(0, 4)
  return (
    <article aria-label={doc.title || '소스 게시물'} className={variant === 'row' ? 'feed-post-row' : undefined}>
      <PostSurface variant={variant}>
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <SourceBadge sourceType={doc.source_type} />
            {doc.channel_kind && doc.channel_key ? (
              <Link to={`/source?kind=${doc.channel_kind}&key=${encodeURIComponent(doc.channel_key)}`}
                className={`min-w-0 max-w-[60%] truncate font-medium text-foreground ${focusLink}`}>{doc.channel}</Link>
            ) : <span className="min-w-0 truncate font-medium text-foreground">{doc.channel || '수집 자료'}</span>}
            <time className="ml-auto shrink-0 text-caption" dateTime={doc.published_at} title={doc.published_at}>
              {formatRelativeTime(doc.published_at)} {timeLabel}
            </time>
          </div>
          <h3 className="text-card-title font-semibold text-pretty break-words">
            <Link to={`/doc/${doc.id}`} className={focusLink}>{doc.title || excerpt.slice(0, 90) || '제목 없는 게시물'}</Link>
          </h3>
          {reading ? <div className="space-y-4">
            <DocumentBody doc={doc} reading={reading} mediaSize="preview" />
            <div className="flex flex-wrap items-center gap-2">
              {tags.map(tag => <EntityChip key={`${tag.entity_id}-${tag.link_type}`} tag={tag} onFilter={onChipFilter} />)}
              <StudyButton documentId={doc.id} /><AddToStudy documentId={doc.id} /><Button asChild variant="ghost" size="sm" className="ml-auto"><Link to={`/doc/${doc.id}`}>자료 상세<ArrowUpRight aria-hidden="true" /></Link></Button>
              {/^https?:\/\//i.test(doc.url) && <Button asChild variant="outline" size="sm"><a href={doc.url} target="_blank" rel="noreferrer">원문 사이트<ArrowUpRight aria-hidden="true" /></a></Button>}
            </div>
          </div> : <Collapsible open={open} onOpenChange={setOpen}>
            {!compact && !open && excerpt && (
              <div className="flex gap-3">
                <div className="min-w-0 flex-1">
                  <span className={`text-caption ${doc.summary ? 'text-hypothesis' : 'text-muted-foreground'}`}>{doc.summary ? 'AI 요약' : '본문 발췌'}</span>
                  <p className="mt-0.5 line-clamp-3 break-words text-sm leading-relaxed text-muted-foreground">{excerpt}</p>
                </div>
                {doc.images[0] && <a href={`${API_BASE}/media/${doc.images[0]}`} target="_blank" rel="noreferrer" className={`shrink-0 self-start ${focusLink}`} aria-label="첨부 이미지 원본 열기">
                  <img src={`${API_BASE}/media/${doc.images[0]}`} alt="게시물 첨부 이미지" width={80} height={64} loading="lazy" className="h-16 w-20 rounded-md object-cover" />
                </a>}
              </div>
            )}
            <CollapsibleContent className="space-y-3">
              <p className="text-caption text-muted-foreground">수집 본문</p>
              <div className="break-words text-reading" tabIndex={0} aria-label="수집 본문"><Markdown>{doc.content || doc.summary || ""}</Markdown></div>
              {doc.images.length > 0 && <div className="flex flex-wrap gap-2">{doc.images.map(img => (
                <a key={img} href={`${API_BASE}/media/${img}`} target="_blank" rel="noreferrer" className={focusLink} aria-label="첨부 이미지 원본 열기">
                  <img src={`${API_BASE}/media/${img}`} alt="게시물 첨부 이미지" width={160} height={100} loading="lazy" className="h-24 w-40 rounded-md object-cover" />
                </a>
              ))}</div>}
            </CollapsibleContent>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {tags.map(tag => <EntityChip key={`${tag.entity_id}-${tag.link_type}`} tag={tag} onFilter={onChipFilter} />)}
              {doc.entities.length > tags.length && <span className="text-caption text-muted-foreground">+{formatNumber(doc.entities.length - tags.length)}</span>}
              <div className="ml-auto flex flex-wrap items-center gap-3"><StudyButton documentId={doc.id} /><AddToStudy documentId={doc.id} />
                {(doc.content || doc.summary) && <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="text-caption text-muted-foreground">
                    {open ? '접기' : '펼쳐 읽기'}<ChevronDown aria-hidden="true" className={`size-3 ${open ? 'rotate-180' : ''}`} />
                  </Button>
                </CollapsibleTrigger>}
                {/^https?:\/\//i.test(doc.url) && <a href={doc.url} target="_blank" rel="noreferrer" className={`inline-flex items-center gap-1 text-xs text-muted-foreground ${focusLink}`}>
                  원문<ArrowUpRight aria-hidden="true" className="size-3" />
                </a>}
              </div>
            </div>
          </Collapsible>}
      </PostSurface>
    </article>
  )
}

export function SystemPost({ item, compact = false, variant = 'card', presentation = 'preview' }: { item: TimelineItem; compact?: boolean; variant?: PostVariant; presentation?: 'preview' | 'reading' }) {
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
            {presentation === 'preview' && !compact && !open && <p className="line-clamp-3 break-words text-sm leading-relaxed text-muted-foreground">{preview(item.body)}</p>}
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
