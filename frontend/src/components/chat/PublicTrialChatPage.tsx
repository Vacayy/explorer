import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { googleLoginUrl } from '@/api/auth'
import { useMemberAccess } from '@/components/auth/MemberAccess'
import { PageContainer } from '@/components/shared/PageContainer'
import { EmptyState, ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { usePublishedDocument } from '@/hooks/usePublishedDocument'
import { usePublishedDocuments } from '@/hooks/usePublishedDocuments'
import { useTrialChat } from '@/hooks/useTrialChat'
import { formatNumber } from '@/utils/format'

type Selection = { id: number; title: string }
function positiveId(value: string | null) {
  return value && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : null
}
function safeCitation(url: string) {
  return /^\/doc\/[1-9]\d*$/.test(url) && Number.isSafeInteger(Number(url.slice(5)))
}

export function PublicTrialChatPage() {
  const access = useMemberAccess()
  const [params] = useSearchParams()
  const scope = access.session?.user ? `${access.session.user.id}:${access.session.user.role}` : 'anonymous'
  const initial = useRef<string | null>(null)
  const changedScope = useRef(false)
  if (['anonymous', 'member', 'operator'].includes(access.status)) {
    if (initial.current === null) initial.current = scope
    else if (initial.current !== scope) changedScope.current = true
  }
  // Do not repopulate cleared selection from a stale URL after account changes.
  const initialDoc = changedScope.current ? null : positiveId(params.get('doc'))
  return <TrialPage key={scope} scope={scope} initialDoc={initialDoc} anonymous={access.status === 'anonymous'} />
}

function TrialPage({ scope, initialDoc, anonymous }: { scope: string; initialDoc: number | null; anonymous: boolean }) {
  const chat = useTrialChat(scope)
  const [params, setParams] = useSearchParams()
  const search = (params.get('search') ?? '').slice(0, 120)
  const cursor = params.get('cursor')
  const [draft, setDraft] = useState('')
  const [searchDraft, setSearchDraft] = useState(search)
  const updateSearch = (query: string, next: string | null = null) => {
    const updated = new URLSearchParams()
    if (initialDoc !== null) updated.set('doc', String(initialDoc))
    if (query) updated.set('search', query)
    if (next !== null) updated.set('cursor', next)
    setParams(updated)
  }
  useEffect(() => { setSearchDraft(search) }, [search])
  const [selected, setSelected] = useState<Selection[]>([])
  const seeded = useRef<number | null>(null)
  const alive = useRef(true)
  const editVersion = useRef(0)
  const docs = usePublishedDocuments(search, cursor)
  const initialQuery = usePublishedDocument(initialDoc)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    if (initialDoc === null || initialQuery.error || initialQuery.isFetching || !initialQuery.data || seeded.current === initialDoc) return
    if (initialQuery.data.id !== initialDoc) return
    seeded.current = initialDoc
    setSelected(current => current.some(item => item.id === initialDoc) || current.length >= 4 ? current
      : [...current, { id: initialDoc, title: initialQuery.data!.title || '제목 없는 문서' }])
  }, [initialDoc, initialQuery.data, initialQuery.error, initialQuery.isFetching])
  const choose = (item: Selection) => setSelected(current => current.some(old => old.id === item.id)
    ? current.filter(old => old.id !== item.id) : current.length < 4 ? [...current, item] : current)
  const resetConversation = () => {
    editVersion.current += 1
    setDraft('')
    void chat.reset()
  }
  const submit = async () => {
    if (chat.sending || selected.length === 0 || !draft.trim() || !chat.session || chat.session.remaining <= 0) return
    const version = editVersion.current
    const sent = await chat.send(draft, { document_ids: selected.map(item => item.id), search_query: search })
    if (sent && alive.current && editVersion.current === version) setDraft('')
  }
  const exhausted = chat.session !== null && chat.session.remaining <= 0
  const docLoading = !docs.error && (!docs.data || docs.isFetching)
  const initialLoading = initialDoc !== null && !initialQuery.error && (!initialQuery.data || initialQuery.isFetching)
  return <PageContainer width="reading" className="[overflow-wrap:anywhere]">
    <header className="space-y-2">
      <h1 className="text-xl font-medium">공개 자료 체험 채팅</h1>
      <p className="text-sm text-ink-2">공개 문서 1~4개를 골라 질문하세요. 답변은 선택한 자료를 바탕으로 작성합니다.</p>
      <p className="text-xs text-ink-2">대화는 이 화면에서만 유지되며 새로고침하거나 화면을 떠나면 사라집니다. 모델 제공자의 보존 정책은 별도로 적용됩니다.</p>
      <Button asChild variant="ghost" size="sm"><Link to="/feed">공개 문서 목록</Link></Button>
    </header>

    <section aria-label="질문에 사용할 공개 자료" className="space-y-3 border-y py-4">
      <h2 className="text-base font-medium">자료 선택</h2>
      <form role="search" className="space-y-2" onSubmit={event => { event.preventDefault(); if (!chat.sending) updateSearch(searchDraft.trim()) }}>
        <Label htmlFor="trial-doc-search">자료 찾기</Label>
        <div className="flex gap-2"><Input id="trial-doc-search" type="search" maxLength={120} value={searchDraft} disabled={chat.sending}
          onChange={event => setSearchDraft(event.target.value)} placeholder="자료 제목 또는 본문 검색" />
          <Button type="submit" variant="outline" disabled={chat.sending}>자료 검색</Button></div>
      </form>
      {initialLoading && <p role="status" className="text-sm">연결된 문서의 공개 상태를 확인하는 중…</p>}
      {initialDoc !== null && initialQuery.error && <ErrorState message="연결된 문서를 확인하지 못했습니다. 공개 자료 목록에서 다시 선택해 주세요."
        onRetry={() => void initialQuery.refetch()} retrying={initialQuery.isFetching || chat.sending} />}
      {docs.error || docs.fetchStatus === 'paused'
        ? <ErrorState message="자료 목록을 불러오지 못했습니다." onRetry={() => void docs.refetch()} retrying={docs.isFetching || chat.sending} />
        : docLoading ? <p role="status" className="text-sm">공개 자료를 불러오는 중…</p>
          : <>
            {docs.data!.items.length === 0 ? <EmptyState message={docs.data!.next_cursor !== null ? '이 구간에는 일치하는 자료가 없습니다. 다음 목록을 확인해 주세요.'
              : search ? '검색 결과가 없습니다.' : '아직 공개된 자료가 없습니다.'} />
              : <ul className="divide-y">{docs.data!.items.map(item => {
                const checked = selected.some(old => old.id === item.id)
                return <li key={item.id} className="flex items-start gap-3 py-3">
                  <Checkbox id={`trial-doc-${item.id}`} checked={checked} disabled={chat.sending || (!checked && selected.length >= 4)}
                    onCheckedChange={() => choose({ id: item.id, title: item.title || '제목 없는 문서' })} />
                  <div className="min-w-0 flex-1 space-y-1"><Label htmlFor={`trial-doc-${item.id}`} className="leading-relaxed">{item.title || '제목 없는 문서'}</Label>
                    <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-2">{item.snippet}</p>
                    <Link className="text-xs underline" to={`/doc/${item.id}`}>문서 읽기</Link></div>
                </li>
              })}</ul>}
            <div className="flex flex-wrap gap-2">
              {cursor !== null && <Button variant="ghost" disabled={chat.sending} onClick={() => updateSearch(search)}>자료 처음부터</Button>}
              {docs.data!.next_cursor !== null && <Button variant="outline" disabled={chat.sending} onClick={() => updateSearch(search, docs.data!.next_cursor)}>다음 자료</Button>}
            </div>
          </>}
      <div aria-label="선택한 자료" className="space-y-2">
        <p className="text-sm font-medium">선택한 자료 {formatNumber(selected.length)}/4</p>
        {selected.length === 0 ? <p className="text-sm text-ink-2">질문에 사용할 문서를 하나 이상 선택해 주세요.</p>
          : <ul className="space-y-1">{selected.map(item => <li key={item.id} className="flex items-center justify-between gap-2 text-sm">
            <span>{item.title}</span><Button size="sm" variant="ghost" disabled={chat.sending} aria-label={`${item.title} 선택 해제`} onClick={() => choose(item)}>해제</Button>
          </li>)}</ul>}
      </div>
    </section>

    <section aria-label="체험 대화" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-base font-medium">대화</h2>
        <Button variant="ghost" size="sm" onClick={resetConversation}>대화 지우기</Button></div>
      <p className="text-xs text-ink-2">대화를 지워도 사용한 체험 횟수는 복원되지 않습니다.</p>
      {chat.loading ? <p role="status">체험 세션을 준비하는 중…</p>
        : chat.session && <p className="text-sm">남은 체험 {formatNumber(chat.session.remaining)} / {formatNumber(chat.session.limit)}회</p>}
      {chat.error && <div className="space-y-2"><ErrorState message={chat.error} />
        <p className="text-xs text-ink-2">선택한 자료가 변경되거나 공개가 취소되었을 수 있습니다. 자료 선택을 다시 확인해 주세요.</p>
        {!chat.session && <Button variant="outline" onClick={() => void chat.reset()}>대화 지우고 체험 다시 확인</Button>}
      </div>}
      {exhausted && <div role="status" className="space-y-2 border-y py-3 text-sm">
        <p>체험 횟수를 모두 사용했습니다.</p>
        {anonymous && <Button asChild variant="outline"><a href={googleLoginUrl('/chat')}>Google 로그인</a></Button>}
        <p className="text-xs text-ink-2">로그인해도 체험 횟수가 초기화되지는 않습니다. 회원 전용 추가 채팅은 아직 준비 중입니다.</p>
      </div>}
      {chat.messages.length === 0 ? <p className="text-sm text-ink-2">아직 질문이 없습니다. 자료를 선택하고 궁금한 점을 적어 주세요.</p>
        : <ol className="divide-y border-y">{chat.messages.map((message, index) => <li key={index} className="space-y-2 py-4">
          <h3 className="text-xs font-medium text-ink-2">{message.role === 'user' ? '질문' : '답변'}</h3>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
          {message.partial && <p className="text-xs text-ink-2">일부 자료를 발췌한 제한된 근거의 답변입니다. 인용 문서를 함께 확인해 주세요.</p>}
          {message.citations && <ul className="space-y-1">{message.citations.filter(citation => safeCitation(citation.url)).map(citation => <li key={citation.id}>
            <Link className="text-sm underline" to={citation.url}>{citation.id} · {citation.title}</Link>
          </li>)}</ul>}
        </li>)}</ol>}
      {chat.sending && <p role="status">선택한 공개 자료로 답변을 작성하는 중…</p>}
      <form className="space-y-2" onSubmit={event => { event.preventDefault(); void submit() }}>
        <Label htmlFor="trial-question">질문</Label>
        <Textarea id="trial-question" value={draft} maxLength={4000} rows={4} disabled={chat.sending || chat.loading || exhausted}
          onChange={event => { editVersion.current += 1; setDraft(event.target.value) }} placeholder="선택한 자료에 대해 질문하세요" />
        <Button type="submit" disabled={chat.sending || chat.loading || !chat.session || exhausted || selected.length === 0 || !draft.trim() || initialLoading}>질문 보내기</Button>
      </form>
    </section>
  </PageContainer>
}
