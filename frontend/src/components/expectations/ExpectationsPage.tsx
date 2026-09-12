import { useRef, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { FlaskConical, ArrowRight, ExternalLink, Loader2 } from 'lucide-react'
import { PageContainer } from '@/components/shared/PageContainer'
import { ErrorState, EmptyState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { StatementForm, Choice, PRODUCTS, LENSES } from '@/components/expectations/StatementForm'
import { useExpectationDocuments, useExpectationDocument, useExpectationStatements, useExpectationJobs, useExpectationWrite, useExpectationComparison, useExpectationHistory, useStatementEvidence } from '@/hooks/useExpectations'
import type { ExpectationDocument, ExpectationStatement } from '@/types'

const KIND = { derived_summary: 'AI 정리본', stored_transcript: '저장 자막', stored_text: '저장 텍스트', empty: '본문 없음' }
const CHANGE: Record<string, string> = { not_comparable: '비교 보류', first_observation: '첫 비교 관측', repetition: '반복 발언 후보', numeric_change: '수치 기대 변화', same_value: '수치 동일', direction_change: '표현 방향 변화', needs_reading: '원문 대조 필요' }
function external(url: string | null) { return url && /^https?:\/\//i.test(url) ? url : undefined }
function Stamp({ value }: { value: string | null }) { return <span>{value ? new Date(value).toLocaleString('ko-KR') : '시각 미상'}</span> }

function EvidenceReader({ doc, onQuote }: { doc: ExpectationDocument; onQuote: (text: string) => void }) {
  const ref = useRef<HTMLPreElement>(null)
  const [selection, setSelection] = useState('')
  function select() {
    const s = window.getSelection()
    setSelection(s && ref.current?.contains(s.anchorNode) && ref.current?.contains(s.focusNode) ? s.toString().slice(0, 4000) : '')
  }
  return <section className="space-y-3 rounded-xl border bg-card p-4" aria-label="저장 원문">
    <div className="flex flex-wrap items-center justify-between gap-2"><Badge variant="outline">{KIND[doc.text_kind]}</Badge>
      {external(doc.source_url) && <Button asChild variant="ghost" size="sm"><a href={external(doc.source_url)} target="_blank" rel="noreferrer">원 출처 <ExternalLink className="size-3" /></a></Button>}</div>
    <h2 className="font-semibold leading-relaxed">{doc.title || `문서 ${doc.id}`}</h2>
    <p className="text-xs text-muted-foreground">발표 <Stamp value={doc.published_at} /> · 수집 <Stamp value={doc.fetched_at} /></p>
    <div className="space-y-1 text-xs text-muted-foreground">{doc.warnings.map(w => <p key={w}>{w}</p>)}</div>
    <pre ref={ref} tabIndex={0} aria-label="원문 텍스트, 문장을 선택해 기록할 수 있습니다" onMouseUp={select} onKeyUp={select} className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/30 p-3 font-sans text-sm leading-7">{doc.text || '저장된 본문이 없습니다.'}</pre>
    <Button variant="outline" size="sm" disabled={selection.length < 5 || !doc.source_text_available} onClick={() => onQuote(selection)}>선택 문장으로 새 발언 기록</Button>
    {doc.attribution_cues.length > 0 && <details><summary className="cursor-pointer text-sm">화자 검토 단서 {doc.attribution_cues.length}개</summary><ul className="mt-2 space-y-2 text-xs text-muted-foreground">{doc.attribution_cues.map((c, i) => <li key={i} className="rounded border p-2">{c.text}<p className="mt-1">원문 위치 {c.start}–{c.end} · 미검증</p></li>)}</ul></details>}
  </section>
}

function Workbench({ id }: { id: number }) {
  const document = useExpectationDocument(id)
  const statements = useExpectationStatements(id)
  const jobs = useExpectationJobs(id)
  const extraction = useExpectationWrite<{ id: string }>('/extractions')
  const job = jobs.data?.[0]
  const cancel = useExpectationWrite(`/jobs/${job?.id}/cancel`)
  const [manual, setManual] = useState<{ quote: string; key: number } | null>(null)
  if (document.isPending) return <Skeleton className="h-96" />
  if (document.isError) return <ErrorState message={document.error.message} onRetry={() => document.refetch()} />
  const doc = document.data
  const pending = job?.state === 'queued' || job?.state === 'running'
  return <div className="space-y-4">
    <EvidenceReader doc={doc} onQuote={quote => setManual({ quote, key: Date.now() })} />
    <div className="flex flex-wrap gap-2">
      <Button disabled={!doc.source_text_available || extraction.isPending || pending} onClick={() => extraction.mutate({ doc_id: id })}>{pending ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />} {pending ? '발언 추출 중…' : 'AI로 발언 추출'}</Button>
      <Button variant="outline" disabled={!doc.source_text_available} onClick={() => setManual({ quote: '', key: Date.now() })}>직접 기록</Button>
      {pending && <Button variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate({})}>추출 중지</Button>}
    </div>
    <p className="text-xs text-muted-foreground">AI 추출은 선택한 문서에서 최대 8개 초안을 만듭니다. 동일한 입력·추출 버전의 결과는 재사용합니다. 직접 기록은 모델을 사용하지 않습니다.</p>
    <div role="status" aria-live="polite" className="text-sm text-muted-foreground">
      {pending && '문서를 읽고 원문 인용을 확인하고 있습니다. 다른 문서로 이동해도 작업은 보존됩니다.'}
      {job?.state === 'done' && `추출 완료 · ${job.result?.statement_ids.length ?? 0}개 초안${job.result?.truncated ? ' · 긴 문서는 앞 24,000자만 분석했습니다.' : ''}${job.result?.skipped ? ` · 인용/형식 검증 실패 ${job.result.skipped}개 제외` : ''}`}
      {job?.state === 'failed' && job.error}
      {job?.state === 'cancelled' && '추출이 중지됐습니다. 다시 실행할 수 있습니다.'}
    </div>
    {(extraction.error || cancel.error || jobs.error) && <p role="alert" className="text-sm text-destructive">{(extraction.error || cancel.error || jobs.error)?.message}</p>}
    {manual && <StatementForm key={manual.key} doc={doc} initialQuote={manual.quote} onSaved={() => setManual(null)} />}
    {statements.isError && <ErrorState message={statements.error.message} onRetry={() => statements.refetch()} />}
    {statements.isPending && <Skeleton className="h-32" />}
    {statements.data?.length === 0 && !manual && <EmptyState message="아직 발언 기록이 없습니다. AI로 추출하거나 원문 문장을 선택해 기록하세요." />}
    {statements.data?.map(s => <details key={`${s.id}-${s.revision}`} className="rounded-xl border bg-card p-3">
      <summary className="cursor-pointer text-sm leading-6"><span className="mr-2 text-xs text-muted-foreground">#{s.id} · {s.job_id ? jobs.data?.find(j => j.id === s.job_id)?.version || '이전 AI 추출' : '직접 기록'} · {s.status === 'approved' ? '검토됨' : s.status === 'rejected' ? '제외됨' : '초안'} · {s.fields.speaker || '화자 미확인'} · {LENSES[s.fields.lens]}</span>{s.fields.claim}</summary>
      <div className="mt-3 space-y-2"><StatementForm doc={doc} statement={s} />
      <Button asChild variant="link" size="sm"><Link to={`/experiments/expectations/review?view=ledger&sid=${s.id}`}>이 발언의 이전 기대와 비교 <ArrowRight className="size-3" /></Link></Button></div></details>)}
  </div>
}

function StatementSummary({ statement, label }: { statement: ExpectationStatement; label: string }) {
  const f = statement.fields
  const [showSource, setShowSource] = useState(false)
  const snapshot = useStatementEvidence(statement.id, showSource)
  return <section className="min-w-0 space-y-2 rounded-xl border p-4"><h3 className="text-sm font-semibold">{label} · {f.speaker || '화자 미확인'}</h3>
    <p className="text-xs text-muted-foreground"><Stamp value={statement.document.published_at} /> · {PRODUCTS[f.product]} · {LENSES[f.lens]} · {f.horizon}</p>
    <p className="text-sm leading-6">{f.claim}</p><blockquote className="border-l-2 border-primary/40 pl-3 text-sm leading-6 text-muted-foreground">{f.quote}</blockquote>
    <p className="text-xs text-muted-foreground">비교 기준: {f.basis} · 수치 {f.value === null ? '미명시' : `${f.value.toLocaleString('ko-KR')} ${f.unit}`}</p>
    {f.conditions && <p className="text-xs">조건: {f.conditions}</p>}
    <Button asChild variant="link" size="sm"><Link to={`/experiments/expectations/review?doc=${statement.document.id}`}>현재 저장 원문 검토</Link></Button>
    <Button variant="outline" size="sm" aria-expanded={showSource} onClick={() => setShowSource(v => !v)}>{showSource ? '당시 원문 접기' : '추출 당시 원문 보기'}</Button>
    {showSource && <div className="space-y-2">
      {snapshot.isPending && <Skeleton className="h-32" />}
      {snapshot.error && <ErrorState message={snapshot.error.message} onRetry={() => snapshot.refetch()} />}
      {snapshot.data && <><p className="text-xs text-muted-foreground">추출 당시 보존본 · 이후 원문이 바뀌어도 이 근거는 유지됩니다.</p><pre tabIndex={0} className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/30 p-3 font-sans text-xs leading-6">{snapshot.data.text}</pre></>}
    </div>}
  </section>
}

function Comparison({ id }: { id: number }) {
  const comparison = useExpectationComparison(id)
  const history = useExpectationHistory(id)
  const write = useExpectationWrite(`/statements/${id}/notes`)
  const [note, setNote] = useState('')
  if (comparison.isPending) return <Skeleton className="h-64" />
  if (comparison.isError) return <ErrorState message={comparison.error.message} onRetry={() => comparison.refetch()} />
  const c = comparison.data
  return <div className="space-y-4">
    <section className="space-y-2 rounded-xl border bg-card p-4"><Badge variant="outline">{CHANGE[c.kind] ?? c.kind}</Badge><p className="text-sm leading-6">{c.reason}</p>
      {c.delta !== null && <p className="text-lg font-semibold">전망 수치 차이 {c.delta > 0 ? '+' : ''}{c.delta.toLocaleString('ko-KR')} ({c.current.fields.unit}; 두 값의 산술 차이)</p>}</section>
    <div className="grid gap-3 xl:grid-cols-2">{c.previous && <StatementSummary statement={c.previous} label="이전" />}<StatementSummary statement={c.current} label="현재" /></div>
    <section className="space-y-3 rounded-xl border bg-card p-4"><h3 className="font-medium">판단과 확인할 것</h3>
      <p className="text-xs text-muted-foreground">사업 관측·가격·수급은 아직 자동 연결하지 않습니다. 확인한 근거와 URL, 남은 질문을 기록하세요. 기대 변화만으로 주가 움직임의 원인을 확정하지 않습니다.</p>
      <label className="block space-y-2 text-sm">내 판단 메모<Textarea value={note} maxLength={3000} onChange={e => setNote(e.target.value)} placeholder="무엇을 확인했고, 무엇이 나오면 판단을 바꿀까?" /></label>
      <Button disabled={!note.trim() || write.isPending} onClick={() => write.mutate({ text: note }, { onSuccess: () => setNote('') })}>메모 저장</Button>
      {write.error && <p role="alert" className="text-sm text-destructive">{write.error.message}</p>}
      {history.error && <ErrorState message={history.error.message} onRetry={() => history.refetch()} />}
      {history.data?.notes.map(n => <div key={n.id} className="whitespace-pre-wrap rounded-lg bg-muted/30 p-3 text-sm"><p className="mb-1 text-xs text-muted-foreground"><Stamp value={n.created_at} /></p>{n.text}</div>)}
      <details><summary className="cursor-pointer text-sm">검토 이력 {history.data?.reviews.length ?? 0}개</summary>{history.data?.reviews.map(r => <p key={r.id} className="mt-2 text-xs text-muted-foreground">#{r.revision} · {r.status} · <Stamp value={r.created_at} /> · {r.note || '추가 메모 없음'}</p>)}</details>
    </section>
  </div>
}

export default function ExpectationsPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'ledger' ? 'ledger' : 'documents'
  const product = ['hbm','dram','nand'].includes(params.get('product') ?? '') ? params.get('product')! : ''
  const docId = Math.max(0, Number(params.get('doc')) || 0)
  const sid = Math.max(0, Number(params.get('sid')) || 0)
  const before = Number(params.get('before')) || undefined
  const docs = useExpectationDocuments(product, before)
  const ledger = useExpectationStatements()
  const [lookup, setLookup] = useState('')
  function update(values: Record<string, string | null>) { setParams(old => { const p = new URLSearchParams(old); Object.entries(values).forEach(([k,v]) => v ? p.set(k,v) : p.delete(k)); return p }) }
  const records = ledger.data?.filter(s => (!product || s.fields.product === product) && s.status !== 'rejected')
  return <PageContainer>
    <Button asChild variant="link" size="sm"><Link to="/experiments/expectations">← 수집 자료 읽기로 돌아가기</Link></Button>
    <header className="space-y-3"><div className="flex items-center gap-2"><FlaskConical className="size-5 text-primary" /><Badge variant="outline">메모리반도체 · 실험실</Badge></div>
      <h1 className="text-2xl font-semibold tracking-tight">무엇에 대한 기대가 바뀌었을까?</h1>
      <p className="text-sm text-muted-foreground">원문에서 발언자를 확인하고, 같은 제품·지표·기간의 기대를 비교합니다.</p>
    </header>
    <div className="flex flex-wrap items-end gap-3">
      <div className="flex gap-2" aria-label="작업 선택"><Button variant={view === 'documents' ? 'default' : 'outline'} onClick={() => update({ view: null })}>자료 검토</Button><Button variant={view === 'ledger' ? 'default' : 'outline'} onClick={() => update({ view: 'ledger' })}>기대 기록</Button></div>
      <div className="min-w-40"><Choice label="제품 필터" value={product || 'all'} choices={{ all:'전체', hbm:'HBM', dram:'일반 DRAM', nand:'NAND·SSD' }} onChange={v => update({ product: v === 'all' ? null : v, before: null })} /></div>
      <form className="flex items-end gap-2" onSubmit={e => { e.preventDefault(); if (Number(lookup) > 0) update({doc:lookup,view:null}) }}><label className="space-y-1 text-xs text-muted-foreground">문서 ID로 열기<Input type="number" min={1} value={lookup} onChange={e => setLookup(e.target.value)} className="w-28" /></label><Button variant="outline" type="submit">열기</Button></form>
    </div>
    <div className="grid items-start gap-6 lg:grid-cols-[19rem_minmax(0,1fr)]">
      <aside aria-label={view === 'documents' ? '문서 목록' : '기대 기록 목록'} className="max-h-80 space-y-3 overflow-y-auto pr-1 lg:sticky lg:top-6 lg:max-h-[70vh]">
        {view === 'documents' ? <>
          <p className="text-xs text-muted-foreground">제품 어휘가 있는 저장 문서 · 최신 저장 순</p>
          {docs.isPending && <Skeleton className="h-64" />}
          {docs.isError && <ErrorState message={docs.error.message} onRetry={() => docs.refetch()} />}
          {docs.data?.items.map(d => <Button key={d.id} variant="ghost" className={`h-auto w-full justify-start whitespace-normal rounded-xl border p-3 text-left ${docId === d.id ? 'bg-accent' : ''}`} onClick={() => update({ doc: String(d.id) })}><div className="min-w-0 space-y-1"><p className="text-xs text-muted-foreground">#{d.id} · {d.source_type} · {KIND[d.text_kind]}</p><p className="text-sm leading-6">{d.title || '제목 없음'}</p></div></Button>)}
          {docs.data?.items.length === 0 && <EmptyState message={docs.data.has_more ? '이번 범위에 후보가 없습니다. 다음 범위를 확인하세요.' : '남은 문서에 후보가 없습니다.'} />}
          <div className="flex gap-2">{before && <Button variant="outline" onClick={() => update({ before: null })}>처음</Button>}{docs.data?.has_more && <Button variant="outline" onClick={() => update({ before: String(docs.data.next_before_id) })}>다음 범위</Button>}</div>
        </> : <>
          <p className="text-xs text-muted-foreground">최근 저장 500개 이내 · 검토 전 초안 포함</p>
          {ledger.isPending && <Skeleton className="h-64" />}
          {ledger.isError && <ErrorState message={ledger.error.message} onRetry={() => ledger.refetch()} />}
          {records?.length === 0 && <EmptyState message="아직 발언 기록이 없습니다. 자료 검토에서 첫 발언을 저장하세요." />}
          {records?.map(s => <Button key={s.id} variant="ghost" className={`h-auto w-full justify-start whitespace-normal rounded-xl border p-3 text-left ${sid === s.id ? 'bg-accent' : ''}`} onClick={() => update({ sid: String(s.id) })}><div className="space-y-1"><p className="text-xs text-muted-foreground">{s.fields.speaker || '화자 미확인'} · {s.status === 'approved' ? '검토됨' : '초안'} · {s.fields.horizon}</p><p className="text-sm leading-6">{s.fields.claim}</p></div></Button>)}
        </>}
      </aside>
      <section aria-label="검토 작업" className="min-w-0">{view === 'documents' ? docId ? <Workbench key={docId} id={docId} /> : <EmptyState message="왼쪽에서 문서를 골라 원문과 발언을 검토하세요. 기존 데이터를 바꾸지 않고 실험 기록만 저장합니다." /> : sid ? <Comparison key={sid} id={sid} /> : <EmptyState message="기록을 선택하면 비교 가능한 이전 기대와 나란히 볼 수 있습니다." />}</section>
    </div>
  </PageContainer>
}
