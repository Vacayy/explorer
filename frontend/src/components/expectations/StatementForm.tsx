import { useId, useState } from 'react'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useExpectationWrite } from '@/hooks/useExpectations'
import type { ExpectationDocument, ExpectationFields, ExpectationStatement } from '@/types'

export const PRODUCTS = { memory: '메모리 전체', hbm: 'HBM', dram: '일반 DRAM', nand: 'NAND·SSD' }
export const LENSES = { business: '사업 전망', valuation: '주가·밸류에이션', psychology: '심리·확신', position: '본인 거래 태도', flows: '수급·파생 해석' }
const METRICS = { demand: '수요', supply: '공급', price: '가격', margin: '수익성', qualification: '인증·경쟁', position: '포지션', other: '기타' }
const AXES = { level: '수준', growth: '성장률', acceleration: '가속·감속', timing: '예상 시점', conviction: '확신', position: '거래 태도' }
export function Choice({ label, value, choices, onChange }: { label: string; value: string; choices: Record<string, string>; onChange: (v: string) => void }) {
  const id = useId()
  return <div className="space-y-1"><label htmlFor={id} className="text-xs text-muted-foreground">{label}</label>
    <Select value={value} onValueChange={onChange}><SelectTrigger id={id} className="w-full"><SelectValue /></SelectTrigger>
      <SelectContent>{Object.entries(choices).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent></Select></div>
}
export function StatementForm({ doc, statement, initialQuote = '', onSaved }: { doc: ExpectationDocument; statement?: ExpectationStatement; initialQuote?: string; onSaved?: () => void }) {
  const [fields, setFields] = useState<ExpectationFields>(statement?.fields ?? { speaker: '', attribution: 'unknown', speaker_quote: '', product: 'memory', target: '메모리 산업', lens: 'business', metric: 'other', axis: 'level', horizon: 'unknown', basis: 'unknown', direction: 'unclear', value: null, unit: '', quote: initialQuote, claim: '', conditions: '' })
  const [note, setNote] = useState(statement?.note ?? '')
  const write = useExpectationWrite(statement ? `/statements/${statement.id}/review` : '/statements')
  function set<K extends keyof ExpectationFields>(key: K, val: ExpectationFields[K]) { setFields(f => ({ ...f, [key]: val })) }
  const exact = fields.quote.length >= 5 && !!doc.text?.includes(fields.quote)
  const stale = !!statement && statement.document.text_sha256 !== doc.text_sha256
  const save = (status: string) => write.mutate(statement ? { ...(status === 'rejected' ? statement.fields : fields), expected_revision: statement.revision, status, note } : { ...fields, doc_id: doc.id, text_sha256: doc.text_sha256 }, { onSuccess: onSaved })
  const input = (key: 'speaker' | 'target' | 'horizon' | 'basis' | 'unit' | 'conditions', label: string) => <label className="space-y-1 text-xs text-muted-foreground">{label}<Input value={fields[key]} onChange={e => set(key, e.target.value)} /></label>
  return <div className="space-y-3 rounded-xl border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">{statement ? `발언 #${statement.id} · ${statement.status === 'approved' ? '검토됨' : statement.status === 'rejected' ? '제외됨' : '초안'}` : '직접 발언 기록'}</h3><span className="text-xs text-muted-foreground">원문과 비교하고 저장하세요</span></div>
    <label className="block space-y-1 text-sm">인용문 — 원문 그대로<Textarea value={fields.quote} onChange={e => set('quote', e.target.value)} rows={3} /></label>
    <p className={exact ? 'text-xs text-muted-foreground' : 'text-xs text-destructive'}>{exact ? '저장 텍스트에 있는 인용문입니다. 화자와 맥락은 별도로 확인하세요.' : '원문에서 연속된 문장을 그대로 복사하세요.'}</p>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{input('speaker', '실제 발언자')}
      <Choice label="발언 관계" value={fields.attribution} choices={{ unknown: '화자 미확인', direct: '직접 발언', reported: '제3자의 발언을 전달' }} onChange={v => set('attribution', v as ExpectationFields['attribution'])} /></div>
    <label className="block space-y-1 text-xs text-muted-foreground">발언자 근거 — 자기소개·서명·인용 표시 원문<Textarea value={fields.speaker_quote} onChange={e => set('speaker_quote', e.target.value)} rows={2} /></label>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Choice label="제품" value={fields.product} choices={PRODUCTS} onChange={v => set('product', v as ExpectationFields['product'])} />{input('target', '대상 기업 또는 산업')}
      <Choice label="관측 층위" value={fields.lens} choices={LENSES} onChange={v => set('lens', v as ExpectationFields['lens'])} />
      <Choice label="쟁점" value={fields.metric} choices={METRICS} onChange={v => set('metric', v as ExpectationFields['metric'])} />
      <Choice label="비교 축" value={fields.axis} choices={AXES} onChange={v => set('axis', v as ExpectationFields['axis'])} />
      {input('horizon', '전망 대상 기간 (2027Q3 / 현재 투자 태도는 current / 미상은 unknown)')}{input('basis', '비교 기준 (예: 서버 DDR5 계약가, YoY)')}
      <Choice label="표현 방향" value={fields.direction} choices={{ up: '상승·확대', down: '하락·축소', flat: '유지·횡보', unclear: '불명확' }} onChange={v => set('direction', v as ExpectationFields['direction'])} />
      <label className="space-y-1 text-xs text-muted-foreground">명시된 전망 수치 (없으면 비움)<Input type="number" step="any" value={fields.value ?? ''} onChange={e => set('value', e.target.value === '' ? null : Number(e.target.value))} /></label>
      {input('unit', '수치 단위·비교 방식')}{input('conditions', '조건·전제')}
    </div>
    <label className="block space-y-1 text-sm">발언 해석<Textarea value={fields.claim} onChange={e => set('claim', e.target.value)} rows={2} /></label>
    {statement && <label className="block space-y-1 text-sm">검토 이유 — 본문 화자 근거가 없으면 출처와 확인 이유<Textarea value={note} onChange={e => setNote(e.target.value)} rows={2} /></label>}
    {stale && <p role="alert" className="text-sm text-destructive">원문이 변경됐습니다. 새 원문에서 다시 추출하세요.</p>}
    {write.error && <p role="alert" className="text-sm text-destructive">{String(write.error.message)}</p>}
    <div className="flex flex-wrap gap-2">
      <Button disabled={!exact || !fields.claim.trim() || write.isPending || stale || (Boolean(statement) && (!fields.speaker.trim() || fields.attribution === 'unknown'))} onClick={() => save('approved')}>{write.isPending ? '저장 중…' : statement ? '원문 확인 후 승인' : '초안으로 저장'}</Button>
      {statement && <Button variant="outline" disabled={write.isPending} onClick={() => save('rejected')}>비교에서 제외</Button>}
    </div>
    {!statement && <p className="text-xs text-muted-foreground">초안으로 저장한 뒤 화자·기간을 확인해 승인하면 비교 원장에 포함됩니다.</p>}
  </div>
}
