import { Markdown } from '@/components/shared/Markdown'
import { API_BASE } from '@/api/client'
import type { FeedDocument } from '@/types'

/** Preserve the stored source text. A video may store an AI digest rather than verbatim captions. */
export function DocumentBody({ doc, reading, mediaSize = 'full' }: { doc: FeedDocument; reading: 'original' | 'summary' | 'digest' | 'transcript'; mediaSize?: 'preview' | 'full' }) {
  const markdown = ['youtube', 'canon', 'note'].includes(doc.source_type)
  const text = reading === 'digest' ? doc.video_digest : reading === 'transcript' ? doc.transcript : reading === 'summary' ? doc.summary : doc.content
  return <div className="space-y-3">
    <p className="text-caption text-muted-foreground">{reading === 'digest' ? 'AI 정리본 · 핵심 요약, 주요 논점, 언급된 항목과 투자 시사점' : reading === 'transcript' ? '수집한 원본 자막' : reading === 'summary' ? '저장된 짧은 요약' : doc.source_type === 'youtube' ? '보관된 영상 본문 · AI 정리본일 수 있습니다' : '수집 원문'}</p>
    {text?.trim() ? reading === 'summary' || (markdown && reading !== 'transcript') ? <Markdown className="[overflow-wrap:anywhere] [&_pre]:overflow-x-auto [&_img]:max-w-full">{text}</Markdown> : <div className="whitespace-pre-wrap text-sm leading-relaxed [overflow-wrap:anywhere]">{text}</div> : <p className="text-sm text-muted-foreground">{reading === 'digest' ? '정리본이 완성되면 여기에 표시됩니다. 원본 자막 탭에서 먼저 읽을 수 있습니다.' : reading === 'transcript' ? '이 영상은 과거 저장 방식으로 원본 자막이 보존되지 않았습니다. AI 정리본이나 유튜브 링크를 확인하세요.' : reading === 'summary' ? '아직 저장된 요약이 없습니다. 원문 보기에서 내용을 확인하세요.' : '수집된 텍스트 본문이 없습니다. 첨부 이미지나 원문 사이트를 확인하세요.'}</p>}
    {reading === 'original' && doc.images.length > 0 && <div className="space-y-3">{doc.images.map(img => <a key={img} href={`${API_BASE}/media/${img}`} target="_blank" rel="noreferrer" className="block rounded-xl focus-visible:outline-2 focus-visible:outline-ring"><img src={`${API_BASE}/media/${img}`} alt="문서 첨부 이미지" loading="lazy" className={`${mediaSize === 'preview' ? 'max-h-80' : 'max-h-[640px]'} max-w-full rounded-xl object-contain`} /></a>)}</div>}
  </div>
}
