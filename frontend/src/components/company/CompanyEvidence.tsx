import { useEffect, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { BoundedArea } from '@/components/shared/Bounded'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { DetailLink } from '@/components/shared/DetailNavigation'
import { InfoTip } from '@/components/shared/InfoTip'
import { useCompanyEvidence } from '@/hooks/useCompanyEvidence'
import { formatNumber } from '@/utils/format'
import type { EvidenceRange } from '@/types'
import { CompanyEvidenceSummary } from './CompanyEvidenceSummary'

const titleLink =
  'block text-left text-sm font-semibold leading-relaxed hover:underline focus-visible:outline-2 focus-visible:outline-primary'

export const sourceLabels: Record<string, string> = {
  telegram: '텔레그램',
  blog: '블로그',
  disclosure: '공시',
  transcript: '컨콜',
  youtube: '유튜브',
  news: '뉴스',
  article: '아티클',
  scrap: '스크랩',
  note: '노트',
  canon: '역사',
  memo: '투자자 메모',
  earnings_release: '실적 발표',
}
export type { EvidenceItem, EvidenceResponse, EvidenceRange } from '@/types'

const ALL = '__all'
/** 목록 날짜 — 올해는 '11/04', 지난해 이전은 '25.11.04'(시안 Dossier-KR-Mentions) */
const shortDay = (d: string) => d.slice(0, 4) === String(new Date().getFullYear()) ? `${d.slice(5, 7)}/${d.slice(8, 10)}` : `${d.slice(2, 4)}.${d.slice(5, 7)}.${d.slice(8, 10)}`

/**
 * 기업 관련 자료 목록 — 저장된 문서·공시만(공개일순). URL ?source·?q·?page가 상태.
 * preview: 개요 칸(3건, 필터 없음) · summary: 기간이 정해졌을 때 기간 AI 요약 버튼(미국 자료 탭만, 국내는 §4.13 결정으로 넣지 않는다)
 */
export function CompanyEvidence({
  company,
  range = {},
  market = 'kr',
  preview = false,
  summary = true,
  moreTo,
  title,
}: {
  company: string
  range?: EvidenceRange
  market?: 'kr' | 'us'
  preview?: boolean
  summary?: boolean
  /** 미리보기 머리 오른쪽 '자료 전체 ›' 링크 */
  moreTo?: string
  title?: string
}) {
  const [sp, setSp] = useSearchParams()
  const source = preview ? '' : sp.get('source') || ''
  const q = preview ? '' : sp.get('q') || ''
  const page = preview ? 1 : Math.max(1, Number(sp.get('page')) || 1)
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const parent = panel.current?.parentElement
    if (parent?.classList.contains('company-research-evidence'))
      parent.scrollTop = 0
  }, [company, range.start, range.end, range.cutoff, range.after, source, q, page])
  const feed = useCompanyEvidence({ company, market, ...range, source, q, page, size: preview ? 3 : 10 })
  const change = (key: string, value: string) =>
    setSp(
      (prev) => {
        const n = new URLSearchParams(prev)
        if (value) n.set(key, value)
        else n.delete(key)
        if (key !== 'page') n.delete('page')
        return n
      },
      { replace: true, preventScrollReset: true },
    )
  const label = title ?? (range.end ? (range.start === range.end ? range.end : `${range.start} ~ ${range.end}`) : '최근 수집 자료')
  const tz = market === 'kr' ? '한국' : '뉴욕'
  return (
    <Card ref={panel} className="min-w-0 gap-0 py-0" aria-label="기업 관련 자료">
      <header className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-3">
        <h2 className="text-section font-semibold">{label}</h2>
        <span className="text-caption text-muted-foreground">
          {range.end ? `${tz} 시간 · ${range.cutoff === 'close' ? '정규장 마감 기준' : '그날 끝까지'}` : '공개일순'}
          {!preview && feed.data && ` · ${formatNumber(feed.data.total)}건`}
        </span>
        <InfoTip label="자료 설명">저장된 문서와 공시만 보여 줍니다. 같은 기간의 자료가 주가 변동의 원인이라는 뜻은 아닙니다. 공개일을 모르는 자료는 뺍니다.</InfoTip>
        <span className="ml-auto" />
        {preview && moreTo && <Link to={moreTo} className="shrink-0 text-xs text-muted-foreground hover:text-foreground">자료 전체 ›</Link>}
      </header>
      <CardContent className="space-y-4 px-4 py-3">
        {!preview && summary && range.start && range.end && <CompanyEvidenceSummary company={company} market={market} range={range} source={source} q={q}
          disabled={feed.isPending || feed.isError || feed.data?.total === 0} total={feed.data?.total} />}

        {!preview && (
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              change('q', String(new FormData(e.currentTarget).get('q') || '').trim())
            }}
          >
            <Select value={source || ALL} onValueChange={(v) => change('source', v === ALL ? '' : v)}>
              <SelectTrigger aria-label="자료 출처" className="w-auto min-w-28">
                <span className="text-muted-foreground">출처</span><SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>전체</SelectItem>
                {Object.entries(sourceLabels).map(([key, l]) => <SelectItem key={key} value={key}>{l}</SelectItem>)}
              </SelectContent>
            </Select>
            <Input
              aria-label="자료 검색"
              placeholder="자료 제목·본문 검색"
              key={q}
              name="q"
              defaultValue={q}
              className="min-w-0 flex-1 basis-40"
            />
            <Button type="submit" variant="outline">검색</Button>
          </form>
        )}
        <div aria-live="polite" aria-busy={feed.isFetching}>
          {feed.isPending ? (
            <div role="status" aria-label="자료 불러오는 중" className="space-y-3 py-2">
              {Array.from({ length: preview ? 3 : 6 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : feed.isError ? (
            <div role="alert" className="space-y-2 py-4 text-sm">
              <p>자료를 불러오지 못했습니다.</p>
              <Button variant="outline" size="sm" onClick={() => void feed.refetch()}>다시 시도</Button>
            </div>
          ) : (
            <>
              {feed.data.items.length === 0 && (
                <div className="flex flex-wrap items-center gap-2 py-6 text-sm text-muted-foreground">
                  <p>
                    {q || source
                      ? '이 조건과 일치하는 자료가 없습니다.'
                      : '이 구간에 확보된 자료가 없습니다. 사건이 없었다는 뜻은 아닙니다.'}
                  </p>
                  {(q || source) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSp((prev) => {
                          const n = new URLSearchParams(prev)
                          ;['source', 'q', 'page'].forEach((k) => n.delete(k))
                          return n
                        }, { replace: true })
                      }}
                    >
                      검색·출처 지우기
                    </Button>
                  )}
                </div>
              )}
              {/* 목록은 상한 안에서 스크롤(미리보기 md · 전체 lg) — 쪽 넘김은 아래 그대로 */}
              <BoundedArea size={preview ? 'md' : 'lg'}>{preview ? <ul>
                {/* 시안 Dossier-KR '최근 수집 자료' — 한 줄 행: 출처 칩 | 제목 | 날짜 */}
                {feed.data.items.map((item) => (
                  <li key={item.id} className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-3 border-t py-2.5 first:border-t-0" data-evidence-row>
                    <span className="inline-flex h-[22px] items-center whitespace-nowrap rounded-md bg-chip px-2 text-xs font-medium text-ink-2">{sourceLabels[item.source_type] || item.source_type}</span>
                    {item.doc_id ? (
                      <DetailLink to={`/doc/${item.doc_id}`} className="min-w-0 truncate text-[13.5px] hover:underline" title={item.title || undefined}>{item.title || '제목 없는 자료'}</DetailLink>
                    ) : item.url && /^https?:\/\//i.test(item.url) ? (
                      <a className="min-w-0 truncate text-[13.5px] hover:underline" href={item.url} target="_blank" rel="noopener noreferrer" title={item.title || undefined}>{item.title || '제목 없는 자료'}</a>
                    ) : (
                      <span className="min-w-0 truncate text-[13.5px]">{item.title || '제목 없는 자료'}</span>
                    )}
                    <time dateTime={item.published_at} className="font-mono text-xs tabular-nums text-muted-foreground">{Number(item.local_date.slice(5, 7))}/{Number(item.local_date.slice(8, 10))}</time>
                  </li>
                ))}
              </ul> : <ul className="divide-y">
                {feed.data.items.map((item) => (
                  <li key={item.id} className="space-y-1 py-3" data-evidence-row>
                    <div className="flex flex-wrap gap-x-2 gap-y-1 text-caption text-muted-foreground">
                      <span>{sourceLabels[item.source_type] || item.source_type}</span>
                      <span className="break-all">{item.publisher}</span>
                      <time dateTime={item.published_at} className="font-mono tabular-nums">
                        {shortDay(item.local_date)}{item.time_precision === 'time' && ` ${new Date(item.published_at).toLocaleTimeString('ko-KR', { timeZone: market === 'kr' ? 'Asia/Seoul' : 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}`}
                      </time>
                      {item.time_precision === 'date' && <span>시각 미상</span>}
                      {item.status !== 'within' && (
                        <span className="font-medium text-primary">
                          {item.status === 'after' ? '선택 시점 이후 공개' : '장 마감 당시 공개 여부 미확인'}
                        </span>
                      )}
                    </div>
                    {item.doc_id ? (
                      <DetailLink to={`/doc/${item.doc_id}`} className={titleLink}>
                        {item.title || '제목 없는 자료'}
                      </DetailLink>
                    ) : item.url && /^https?:\/\//i.test(item.url) ? (
                      <a className={titleLink} href={item.url} target="_blank" rel="noopener noreferrer">
                        {item.title || '제목 없는 자료'} ↗
                      </a>
                    ) : (
                      <p className="text-sm font-semibold leading-relaxed">{item.title || '제목 없는 자료'}</p>
                    )}
                    {/* 미리보기가 제목으로 시작하면 제목 뒤만(시안: 제목을 두 번 쓰지 않는다) */}
                    {(() => {
                      const t = item.title?.trim() ?? ''
                      const body = (t && item.excerpt?.startsWith(t) ? item.excerpt.slice(t.length) : item.excerpt ?? '').trim()
                      return body && body !== t ? <p className="line-clamp-3 break-words text-[13px] leading-relaxed text-ink-2">{body}</p> : null
                    })()}
                  </li>
                ))}
              </ul>}</BoundedArea>
              {!preview && (feed.data.has_more || page > 1) && (
                <div className="flex items-center justify-between">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => change('page', String(page - 1))}>‹ 이전</Button>
                  <span className="font-mono text-caption tabular-nums">{page} 페이지</span>
                  <Button variant="outline" size="sm" disabled={!feed.data.has_more} onClick={() => change('page', String(page + 1))}>다음 ›</Button>
                </div>
              )}
            </>
          )}
        </div>
        {!preview && feed.data && (
          <details className="border-t pt-3 text-caption text-muted-foreground">
            <summary className="cursor-pointer">자료 보유 범위 확인</summary>
            <ul className="mt-3 space-y-2">
              {feed.data.coverage.map((c) => (
                <li key={c.source}>
                  {sourceLabels[c.source] || c.source}: {c.first} ~ {c.last} · {formatNumber(c.count)}건
                </li>
              ))}
            </ul>
            <p className="mt-3">
              보유 기간은 수집 완전성을 뜻하지 않습니다. 공개일 미확인 {feed.data.undated_count}건은 제외했습니다.
            </p>
            {feed.data.uncertain_count > 0 && (
              <p>선택일 공개시각 미상 {feed.data.uncertain_count}건 · ‘이후 해설도 보기’에서 별도로 확인할 수 있습니다.</p>
            )}
          </details>
        )}
      </CardContent>
    </Card>
  )
}
