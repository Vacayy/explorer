import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowUpRight, BookOpen, History, MessageCircle, RefreshCw } from 'lucide-react'
import { PageContainer } from '@/components/shared/PageContainer'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Choice, PRODUCTS } from '@/components/expectations/StatementForm'
import ExpectationsPage from '@/components/expectations/ExpectationsPage'
import { useExpectationDocument } from '@/hooks/useExpectations'
import { useMemoryReading, useReadingHistory, useReadingDiscussion } from '@/hooks/useMemoryReading'
import type { ReadingItem } from '@/types'

const SOURCE: Record<string,string> = { telegram:'텔레그램', blog:'블로그', youtube:'유튜브' }
function stamp(value: string | null) {
  if (!value) return '시각 미상'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '시각 미상' : new Intl.DateTimeFormat('ko-KR', { year:'numeric', month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit' }).format(date)
}
function SourceCard({ item, onRead, onHistory, onAsk, busy }: { item: ReadingItem; onRead: () => void; onHistory: () => void; onAsk: () => void; busy: boolean }) {
  const d = item.document
  return <article className="flex flex-col gap-3 rounded-xl border bg-card p-5">
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><Badge variant="outline">{SOURCE[d.source_type]}</Badge><span>{item.channel_name}</span><span>발표 {stamp(d.published_at)}</span></div>
    <h2 className="text-base font-semibold leading-7">{d.title || item.summary?.slice(0, 100) || '제목 없는 수집 자료'}</h2>
    <p className="whitespace-pre-wrap text-sm leading-7">{item.summary || item.excerpt || '본문이 없는 자료입니다. 원 출처를 확인하세요.'}</p>
    <p className="text-xs text-muted-foreground">{item.summary ? '저장된 AI 요약' : '메모리 관련 본문 발췌'}{d.text_kind === 'derived_summary' ? ' · 원 자막 대신 AI 정리본이 보존되어 있습니다.' : ''}{item.copies.length > 0 ? ` · 같은 본문 ${item.copies.length}건 묶음` : ''}</p>
    <div className="mt-auto flex flex-wrap gap-2 pt-1">
      <Button size="sm" variant="outline" onClick={onRead}><BookOpen /> 읽기</Button>
      <Button size="sm" variant="ghost" onClick={onHistory}><History /> 과거 자료와 비교</Button>
      <Button size="sm" variant="ghost" disabled={busy || !d.text_length} onClick={onAsk}><MessageCircle /> 이 자료로 대화</Button>
    </div>
  </article>
}

function ReadingDesk() {
  const [params, setParams] = useSearchParams()
  const days = [1,7,30].includes(Number(params.get('days'))) ? Number(params.get('days')) : 7
  const product = ['hbm','dram','nand'].includes(params.get('product') || '') ? params.get('product')! : ''
  const source = Object.keys(SOURCE).includes(params.get('source') || '') ? params.get('source')! : ''
  const readId = Number(params.get('read') || params.get('doc')) || 0
  const historyId = Number(params.get('history')) || 0
  const reading = useMemoryReading(days, product, source)
  const document = useExpectationDocument(readId)
  const history = useReadingHistory(historyId)
  const discussion = useReadingDiscussion()
  const [question, setQuestion] = useState('')
  const data = reading.data
  const ids = data?.discussion_ids || []
  const period = days === 1 ? '최근 24시간' : `최근 ${days}일`
  function update(values: Record<string,string|null>) { setParams(old => { const p = new URLSearchParams(old); Object.entries(values).forEach(([k,v]) => v ? p.set(k,v) : p.delete(k)); return p }) }
  function ask(q: string, docIds: number[]) { if (!discussion.isPending && docIds.length) discussion.mutate({ question:q, ids:docIds }) }
  const topic = product ? PRODUCTS[product as keyof typeof PRODUCTS] : '메모리반도체'
  const scope = data ? `첨부 자료 범위: ${stamp(data.since)} ~ ${stamp(data.as_of)} 발표분.` : ''
  return <PageContainer>
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-2"><p className="text-sm text-muted-foreground">내가 모은 정보로 읽고, 질문하기</p><h1 className="text-2xl font-semibold tracking-tight">메모리 리서치</h1><p className="text-sm text-muted-foreground">텔레그램·블로그·유튜브의 최근 이야기와 과거 기록을 한곳에서.</p></div>
      <Button asChild size="sm" variant="ghost"><Link to="/experiments/expectations/review">발언 검토 도구</Link></Button>
    </header>
    <div className="flex flex-wrap items-end gap-3">
      <div className="w-36"><Choice label="읽을 기간" value={String(days)} choices={{ '1':'최근 24시간', '7':'최근 7일', '30':'최근 30일' }} onChange={v => update({days:v})} /></div>
      <div className="w-40"><Choice label="제품" value={product || 'all'} choices={{all:'메모리 전체',hbm:'HBM',dram:'일반 DRAM',nand:'NAND·SSD'}} onChange={v => update({product:v==='all'?null:v})} /></div>
      <div className="w-36"><Choice label="자료 출처" value={source || 'all'} choices={{all:'모든 출처',...SOURCE}} onChange={v => update({source:v==='all'?null:v})} /></div>
      <Button variant="ghost" size="sm" disabled={reading.isFetching} onClick={() => reading.refetch()}><RefreshCw className={reading.isFetching ? 'animate-spin' : ''} /> 새 자료 확인</Button>
    </div>
    <section className="space-y-4 rounded-xl border bg-card p-5" aria-label="수집 자료에 질문">
      <div className="space-y-1"><h2 className="font-semibold">{period}, 무엇을 알아두면 좋을까?</h2>
        {data && <p className="text-xs leading-6 text-muted-foreground">메모리 관련 언급이 있는 자료 {data.matched}건 · {Object.entries(data.source_counts).map(([k,v]) => `${SOURCE[k]} ${v}건`).join(' / ') || '해당 기간 자료 없음'}{data.duplicates ? ` · 동일 본문 ${data.duplicates}건 묶음` : ''}<br />최근 수집 {stamp(data.latest_fetched_at)} · 조회 기준 {stamp(data.as_of)}{data.truncated ? ' · 조회 상한에 도달해 일부 자료만 확인했습니다.' : ''}</p>}
      </div>
      <Button disabled={!ids.length || discussion.isPending} onClick={() => ask(`첨부한 ${topic} 수집 자료를 읽고 지금 알아둘 이야기를 3~5개로 정리해줘. 출처별 주장과 반복 전달을 구분하고, 기대·걱정·투자 태도의 차이와 다음에 확인할 질문을 원문 근거와 함께 알려줘. 첨부 표본을 전체 시장 의견으로 일반화하지 마.\n\n${scope}`, ids)}><BookOpen /> {discussion.isPending ? '자료를 대화에 연결하는 중…' : `${period} 이야기 정리해줘`}</Button>
      <p className="text-xs text-muted-foreground">소스가 한쪽에 치우치지 않도록 최근 자료 최대 8개를 골라 대화에 첨부합니다.</p>
      <form className="space-y-2" onSubmit={e => { e.preventDefault(); if (question.trim()) ask(`${question.trim()}\n\n${scope} 첨부는 이 범위에서 고른 ${topic} 자료다. 필요하면 과거 수집 자료도 찾아 대조해줘.`,ids) }}>
        <label htmlFor="memory-reading-question" className="block text-sm">수집한 자료에 질문</label><Textarea id="memory-reading-question" value={question} onChange={e => setQuestion(e.target.value)} placeholder="HBM 수요 전망은 그대로인데 왜 주가를 걱정하는 거야?" rows={2} />
        <Button type="submit" variant="outline" disabled={!question.trim() || !ids.length || discussion.isPending}><MessageCircle /> 이 자료들로 질문하기</Button>
      </form>
      {discussion.error && <ErrorState message="대화를 시작하지 못했습니다. 입력은 보존되어 있습니다." onRetry={() => discussion.variables && discussion.mutate(discussion.variables)} />}
      {discussion.isPending && <p role="status" className="text-sm text-muted-foreground">선택한 자료를 첨부하고 있습니다. 대화 화면에서 답변을 이어서 확인합니다.</p>}
    </section>
    {reading.isPending && <div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-60" /><Skeleton className="h-60" /></div>}
    {reading.error && <ErrorState message={reading.error.message} onRetry={() => reading.refetch()} />}
    {data?.items.length === 0 && <div className="space-y-2"><EmptyState message="이 기간·제품의 저장 자료가 없습니다. 기간이나 출처 범위를 넓혀보세요." /><Button variant="outline" onClick={() => update({days:'30',source:null,product:null})}>최근 30일 전체 자료 보기</Button></div>}
    {data && data.items.length > 0 && <><div className="flex justify-between text-sm text-muted-foreground"><span>{period} 읽을 자료</span><span>발표 최신순 · 최대 24건</span></div><div className="grid gap-4 lg:grid-cols-2">{data.items.map(item => <SourceCard key={item.document.id} item={item} busy={discussion.isPending} onRead={() => update({read:String(item.document.id)})} onHistory={() => update({history:String(item.document.id)})} onAsk={() => ask(`첨부한 자료의 핵심 주장과 근거를 정리하고, 기대·우려·투자 태도를 구분해서 설명해줘. 실제 발언자와 전달 채널을 구분하고, 내가 이어서 확인하면 좋을 질문도 알려줘.`,[item.document.id])} />)}</div></>}
    <Sheet open={readId>0} onOpenChange={open => !open && update({read:null,doc:null})}>
      <SheetContent className="overflow-y-auto sm:max-w-2xl"><SheetHeader><SheetTitle>{document.data?.title || '수집 자료 읽기'}</SheetTitle><SheetDescription>저장된 본문을 읽고 바로 질문할 수 있습니다.</SheetDescription></SheetHeader>
        <div className="space-y-4 p-4">{document.isPending && <Skeleton className="h-80" />}{document.error && <ErrorState message={document.error.message} onRetry={() => document.refetch()} />}
          {document.data && <><p className="text-xs text-muted-foreground">발표 {stamp(document.data.published_at)} · 수집 {stamp(document.data.fetched_at)}{document.data.text_kind==='derived_summary' ? ' · AI 정리본(직접 발언 원문 아님)' : ''}</p>
            <Button disabled={discussion.isPending || !document.data.text_length} onClick={() => ask('이 자료의 핵심과 내가 주목할 기대·우려를 원문 근거와 함께 설명해줘.',[readId])}><MessageCircle /> 이 자료로 대화</Button>
            {document.data.source_url && /^https?:\/\//.test(document.data.source_url) && <Button asChild variant="ghost"><a href={document.data.source_url} target="_blank" rel="noreferrer">원 출처 <ArrowUpRight /></a></Button>}
            <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-8">{document.data.text || '저장된 본문이 없습니다.'}</pre></>}
          {discussion.error && <p role="alert" className="text-sm text-destructive">대화를 시작하지 못했습니다. 다시 시도하세요.</p>}
        </div>
      </SheetContent>
    </Sheet>
    <Sheet open={historyId>0} onOpenChange={open => !open && update({history:null})}>
      <SheetContent className="overflow-y-auto sm:max-w-2xl"><SheetHeader><SheetTitle>과거에는 어떤 이야기를 했을까?</SheetTitle><SheetDescription>같은 수집 소스의 과거 관련 자료를 함께 읽습니다.</SheetDescription></SheetHeader>
        <div className="space-y-4 p-4">{history.isPending && <Skeleton className="h-80" />}{history.error && <ErrorState message={history.error.message} onRetry={() => history.refetch()} />}
          {history.data && <><p className="text-sm font-medium">{history.data.current.channel_name}</p><p className="text-xs leading-6 text-muted-foreground">{history.data.note}{history.data.truncated ? ' 조회 상한에 도달했습니다.' : ''}</p>
            <p className="text-sm leading-6">현재 자료: {history.data.current.document.title}</p>
            {history.data.previous.length === 0 ? <EmptyState message="이전 관련 자료를 찾지 못했습니다. 변화로 단정하지 않고 현재 자료부터 질문할 수 있습니다." /> : history.data.previous.map(item => <article key={item.document.id} className="space-y-2 rounded-xl border p-4"><p className="text-xs text-muted-foreground">{stamp(item.document.published_at)}</p><h3 className="font-medium">{item.document.title}</h3><p className="text-sm leading-7">{item.summary || item.excerpt}</p><Button size="sm" variant="ghost" onClick={() => update({history:null,read:String(item.document.id)})}>본문 읽기</Button></article>)}
            <Button disabled={discussion.isPending} onClick={() => ask(`첨부한 현재 자료와 같은 수집 소스의 과거 자료를 시간순으로 대조해줘. 실제 화자가 같은지 먼저 확인하고, 같은 제품·쟁점·전망 기간의 기대가 달라졌는지, 우려만 추가됐는지, 투자 태도만 달라졌는지 구분해줘. 비교 근거가 부족하면 변화를 만들지 말고 확인된 차이만 원문과 함께 설명해줘.`,[historyId,...history.data.previous.map(i=>i.document.id)])}><MessageCircle /> {history.data.previous.length ? '이 자료들을 비교해줘' : '현재 자료로 질문하기'}</Button>
            {discussion.error && <p role="alert" className="text-sm text-destructive">대화를 시작하지 못했습니다. 다시 시도하세요.</p>}
          </>}
        </div>
      </SheetContent>
    </Sheet>
  </PageContainer>
}

export default function MemoryReadingPage() {
  const [params] = useSearchParams()
  // Existing review deep links remain usable; new visits start with reading.
  return params.has('sid') || ['ledger','review'].includes(params.get('view') || '') ? <ExpectationsPage /> : <ReadingDesk />
}
