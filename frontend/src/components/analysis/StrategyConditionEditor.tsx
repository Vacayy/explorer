import { useId, type ReactNode } from 'react'
import { ChevronDown, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { StrategyCondition, StrategyDefinition } from '@/components/analysis/types'

const OPTIONS: Record<string, string> = { up: '상향', down: '하향', both: '양방향', high: '고가', low: '저가', close: '종가', open: '시가' }

/** 시안 Discover '내 조건' 카드: 번호·이름 + 오른쪽 수정·제거·스위치(toggle) / 설정 한 줄(12 ink-2) / 집계 칩(footer). */
export function StrategyConditionEditor({ condition, definition, busy, onChange, onRemove, number, toggle, footer }: {
  condition: StrategyCondition; definition: StrategyDefinition; busy: boolean; onChange: (next: StrategyCondition) => void; onRemove: () => void
  number?: number; toggle?: ReactNode; footer?: ReactNode
}) {
  const id = useId()
  return <fieldset disabled={busy} className="flex min-w-0 flex-col gap-2 border p-3">
    <legend className="sr-only">{definition.label} 설정</legend>
    <Collapsible className="flex flex-col gap-3"><div className="flex items-start justify-between gap-2"><div className="min-w-0 space-y-1"><h4 className="break-keep text-[13.5px] font-medium">{number != null && `${number}. `}{definition.label}</h4><p className="text-xs text-ink-2">{[...Object.entries(condition.params).map(([key, value]) => `${definition.parameters[key]?.label ?? key} ${OPTIONS[String(value)] ?? (typeof value === 'boolean' ? value ? '예' : '아니요' : value)}`), condition.within_days === 1 ? '기준일 충족' : `최근 ${condition.within_days || '—'}거래일 중 충족`].join(' · ')}</p></div>
      <div className="-mr-1 -mt-1 flex shrink-0 items-center"><CollapsibleTrigger asChild><Button type="button" variant="ghost" size="xs" className="text-ink-2 max-md:min-h-9" aria-label={`${definition.label} 조건 수정`}>수정<ChevronDown className="size-3" /></Button></CollapsibleTrigger><Button type="button" variant="ghost" size="icon-xs" className="text-ink-3 max-md:size-9" aria-label={`${definition.label} 제거`} onClick={onRemove}><X className="size-3.5" /></Button>{toggle && <span className="ml-1 flex h-7 items-center">{toggle}</span>}</div></div>
    <CollapsibleContent className="space-y-3 border-t pt-3">
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Object.entries(definition.parameters).map(([key, parameter]) => <div key={key} className="min-w-0 space-y-1.5"><Label htmlFor={`${id}-${key}`}>{parameter.label}</Label>
        {parameter.options ? <Select disabled={busy} value={String(condition.params[key] ?? '')} onValueChange={value => onChange({ ...condition, params: { ...condition.params, [key]: value } })}><SelectTrigger id={`${id}-${key}`}><SelectValue /></SelectTrigger><SelectContent>{parameter.options.map(option => <SelectItem key={option} value={option}>{OPTIONS[option] ?? option}</SelectItem>)}</SelectContent></Select>
          : parameter.type === 'boolean' ? <Checkbox id={`${id}-${key}`} disabled={busy} checked={condition.params[key] === true} onCheckedChange={value => onChange({ ...condition, params: { ...condition.params, [key]: value === true } })} />
          : <Input id={`${id}-${key}`} type={parameter.type === 'string' ? 'text' : 'number'} required min={parameter.min} max={parameter.max} step={parameter.step ?? (parameter.type === 'integer' ? 1 : 'any')} value={String(condition.params[key] ?? '')} onChange={event => onChange({ ...condition, params: { ...condition.params, [key]: parameter.type === 'string' || event.target.value === '' ? event.target.value : Number(event.target.value) } })} />}
      </div>)}
      {definition.timeframe === '1d' && definition.category !== '순위종목' && <div className="space-y-1.5"><Label htmlFor={`${id}-within`}>충족을 확인할 기간 (거래일)</Label><Input id={`${id}-within`} type="number" required min={1} max={250} step={1} value={condition.within_days || ''} onChange={event => onChange({ ...condition, within_days: Number(event.target.value) })} /><p className="text-caption text-muted-foreground">1은 기준일, 2 이상은 기간 중 한 번 이상</p></div>}
    </div>
    <p className="text-caption text-muted-foreground">계산 기준 · {definition.description}</p>
    </CollapsibleContent></Collapsible>
    {footer}
    {!definition.available && <p className="text-caption text-warn">필요한 자료가 없는 종목은 미평가로 표시합니다.</p>}
  </fieldset>
}
