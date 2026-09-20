import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Markdown } from '@/components/shared/Markdown'
import type { FeedDocument } from '@/types'
import { CompanyEvidenceSummary } from './CompanyEvidenceSummary'

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
}
export interface EvidenceItem {
  id: string
  doc_id: number | null
  title: string
  url: string
  excerpt: string
  source_type: string
  publisher: string
  published_at: string
  local_date: string
  time_precision: 'date' | 'time'
  status: 'within' | 'after' | 'uncertain'
  relation: string
}
interface EvidenceResponse {
  items: EvidenceItem[]
  total: number
  page: number
  has_more: boolean
  coverage: { source: string; first: string; last: string; count: number }[]
  undated_count: number
  uncertain_count: number
  timezone: string
}
export interface EvidenceRange {
  start?: string
  end?: string
  cutoff?: 'end' | 'close'
  after?: boolean
}
export function CompanyEvidence({
  company,
  range = {},
  market = 'kr',
  preview = false,
}: {
  company: string
  range?: EvidenceRange
  market?: 'kr' | 'us'
  preview?: boolean
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
  }, [
    company,
    range.start,
    range.end,
    range.cutoff,
    range.after,
    source,
    q,
    page,
  ])
  const [opened, setOpened] = useState<EvidenceItem | null>(null)
  const trigger = useRef<HTMLButtonElement | null>(null)
  const params = {
    company,
    market,
    ...range,
    source,
    q,
    page,
    size: preview ? 3 : 20,
  }
  const feed = useQuery({
    queryKey: ['company-evidence', params],
    queryFn: async ({ signal }) =>
      (
        await api.get<EvidenceResponse>('/api/spine/feed/company-evidence', {
          params,
          signal,
        })
      ).data,
    staleTime: 60_000,
  })
  const doc = useQuery({
    queryKey: ['spine', 'doc', String(opened?.doc_id)],
    queryFn: async ({ signal }) =>
      (
        await api.get<FeedDocument>(`/api/spine/doc/${opened?.doc_id}`, {
          signal,
        })
      ).data,
    enabled: !!opened?.doc_id,
    staleTime: 300_000,
    refetchOnWindowFocus: false,
  })
  const change = (key: string, value: string) =>
    setSp(
      (prev) => {
        const n = new URLSearchParams(prev)
        value ? n.set(key, value) : n.delete(key)
        if (key !== 'page') n.delete('page')
        return n
      },
      { replace: true },
    )
  const label = range.end ? `${range.start} ~ ${range.end}` : '최근 수집 자료'
  return (
    <Card ref={panel} className="min-w-0" aria-label="기업 관련 자료">
      <CardHeader>
        <CardTitle>{label}</CardTitle>
        <p className="text-caption text-muted-foreground">
          {range.end
            ? `${market === 'kr' ? '한국' : '뉴욕'} 시간 · ${range.cutoff === 'close' ? '정규장 마감 기준' : '선택일 종료 기준'}`
            : '공개일순 · 저장된 자료와 공시'}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {!preview && range.start && range.end && <CompanyEvidenceSummary company={company} market={market} range={range} source={source} q={q}
          disabled={feed.isPending || feed.isError || feed.data?.total === 0}
          onRead={(item, button) => { trigger.current = button; setOpened(item) }} />}

        {!preview && (
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              change(
                'q',
                String(new FormData(e.currentTarget).get('q') || '').trim(),
              )
            }}
          >
            <label className="text-caption">
              출처
              <select
                aria-label="자료 출처"
                className="ml-2 rounded-md border bg-background p-2"
                value={source}
                onChange={(e) => change('source', e.target.value)}
              >
                <option value="">전체</option>
                {Object.entries(sourceLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <Input
              aria-label="기간 내 자료 검색"
              placeholder="자료 제목·본문 검색"
              key={q}
              name="q"
              defaultValue={q}
              className="min-w-0 flex-1 basis-40"
            />
            <Button type="submit" variant="outline">
              검색
            </Button>
          </form>
        )}
        <div aria-live="polite" aria-busy={feed.isFetching}>
          {feed.isPending ? (
            <p className="py-8 text-sm text-muted-foreground">
              자료를 불러오는 중입니다.
            </p>
          ) : feed.isError ? (
            <div role="alert">
              <p>자료 조회에 실패했습니다.</p>
              <Button variant="outline" onClick={() => void feed.refetch()}>
                다시 시도
              </Button>
            </div>
          ) : (
            <>
              {!preview && (
                <p className="text-caption text-muted-foreground">
                  {feed.data.total.toLocaleString()}건 · 제목·본문에서 검색 ·
                  공개일순
                </p>
              )}
              {feed.data.items.length === 0 && (
                <div className="py-8 text-sm text-muted-foreground">
                  <p>
                    {q || source
                      ? '이 조건과 일치하는 자료가 없습니다.'
                      : '이 구간에 확보된 자료가 없습니다. 사건이 없었다는 뜻은 아닙니다.'}
                  </p>
                  {(q || source) && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setSp(
                          (prev) => {
                            const n = new URLSearchParams(prev)
                            ;['source', 'q', 'page'].forEach((k) => n.delete(k))
                            return n
                          },
                          { replace: true },
                        )
                      }}
                    >
                      검색·출처 초기화
                    </Button>
                  )}
                </div>
              )}
              <ul className="divide-y">
                {feed.data.items.map((item) => (
                  <li key={item.id} className="space-y-2 py-4">
                    <div className="flex flex-wrap gap-x-2 gap-y-1 text-caption text-muted-foreground">
                      <span>
                        {sourceLabels[item.source_type] || item.source_type}
                      </span>
                      <span className="break-all">{item.publisher}</span>
                      <time dateTime={item.published_at}>
                        {item.local_date}{item.time_precision === 'time' && ` ${new Date(item.published_at).toLocaleTimeString('ko-KR', { timeZone: market === 'kr' ? 'Asia/Seoul' : 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}`}
                      </time>
                      {item.time_precision === 'date' && <span>시각 미상</span>}
                    </div>
                    {item.status !== 'within' && (
                      <p className="text-caption font-medium text-primary">
                        {item.status === 'after'
                          ? '선택 시점 이후 공개'
                          : '장 마감 당시 공개 여부 미확인'}
                      </p>
                    )}
                    <button
                      className="text-left text-sm font-semibold leading-relaxed hover:underline focus-visible:outline-2 focus-visible:outline-primary"
                      onClick={(e) => {
                        trigger.current = e.currentTarget
                        setOpened(item)
                      }}
                    >
                      {item.title || '제목 없는 자료'}
                    </button>
                    {item.excerpt && (
                      <p className="line-clamp-3 whitespace-pre-line break-words text-sm leading-relaxed text-muted-foreground">
                        {item.excerpt}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              {!preview && (
                <div className="flex items-center justify-between">
                  <Button
                    variant="outline"
                    disabled={page <= 1}
                    onClick={() => change('page', String(page - 1))}
                  >
                    이전
                  </Button>
                  <span className="text-caption">{page} 페이지</span>
                  <Button
                    variant="outline"
                    disabled={!feed.data.has_more}
                    onClick={() => change('page', String(page + 1))}
                  >
                    다음
                  </Button>
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
                  {sourceLabels[c.source] || c.source}: {c.first} ~ {c.last} ·{' '}
                  {c.count.toLocaleString()}건
                </li>
              ))}
            </ul>
            <p className="mt-3">
              보유 기간은 수집 완전성을 뜻하지 않습니다. 공개일 미확인{' '}
              {feed.data.undated_count}건은 제외했습니다. 수출입 통계는
              기업·공개시점 연결을 확보한 뒤 제공합니다.
            </p>
            {feed.data.uncertain_count > 0 && (
              <p>
                선택일 공개시각 미상 {feed.data.uncertain_count}건 · ‘이후
                해설도 보기’에서 별도로 확인할 수 있습니다.
              </p>
            )}
          </details>
        )}
        <p className="text-caption text-muted-foreground">
          같은 기간의 자료가 주가 변동의 원인이라는 뜻은 아닙니다.
        </p>
      </CardContent>
      <Dialog
        open={!!opened}
        onOpenChange={(open) => {
          if (!open) setOpened(null)
        }}
      >
        <DialogContent
          className="max-h-[85dvh] overflow-y-auto sm:max-w-3xl"
          onCloseAutoFocus={(e) => {
            e.preventDefault()
            trigger.current?.focus({ preventScroll: true })
          }}
        >
          <DialogHeader>
            <DialogTitle>{opened?.title || '자료 읽기'}</DialogTitle>
            <DialogDescription>
              {opened?.publisher} · {opened?.published_at} ·{' '}
              {opened?.time_precision === 'date'
                ? '공개시각 미상'
                : '공개 시점'}
            </DialogDescription>
          </DialogHeader>
          {opened?.status !== 'within' && (
            <p className="text-sm text-primary">
              {opened?.status === 'after'
                ? '선택 시점 이후에 공개된 자료입니다.'
                : '장 마감 당시 공개 여부가 확인되지 않았습니다.'}
            </p>
          )}
          {opened?.doc_id ? (
            doc.isPending ? (
              <p>원문을 불러오는 중입니다.</p>
            ) : doc.isError ? (
              <Button onClick={() => void doc.refetch()}>
                원문 다시 불러오기
              </Button>
            ) : (
              <Markdown>
                {doc.data?.transcript ||
                  doc.data?.content ||
                  '저장된 본문이 없습니다.'}
              </Markdown>
            )
          ) : (
            <p className="text-sm">
              공시 전문은 DART 원문에서 확인할 수 있습니다.
            </p>
          )}
          {opened && /^https?:\/\//i.test(opened.url) && (
            <a
              className="text-sm text-primary underline"
              href={opened.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              원문 사이트 열기 ↗
            </a>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  )
}
