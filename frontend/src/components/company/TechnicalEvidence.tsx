import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { evidenceValue, EXCLUSION_LABELS } from '@/components/analysis/strategyEvidence'
import { readingEvidence, SCAN_STATUS, type ReadingEvidence } from '@/components/company/scanEvidence'
import type { ScanEntry } from '@/components/company/TechnicalScan'

export function TechnicalEvidence({ ids, entries, asOf, priceLabels }: {
  ids: string[]; entries: ScanEntry[]; asOf: string | null; priceLabels: Record<string, string>
}) {
  const [opened, setOpened] = useState<ReadingEvidence | null>(null)
  const trigger = useRef<HTMLButtonElement | null>(null)
  return <>
    <div className="flex flex-wrap gap-1.5">
      {readingEvidence(ids, entries, priceLabels).map(item => {
        const label = `${item.label}${item.observation != null ? ` ${evidenceValue(item.observation)}${item.unit ?? ''}` : ''} · ${item.state}`
        return item.conditions.length ? <Button key={item.id} variant="outline" size="sm" className="h-auto min-h-11 whitespace-normal px-2 py-1 text-caption font-normal" onClick={event => { trigger.current = event.currentTarget; setOpened(item) }} aria-label={`${label} · 계산 근거 보기`}>{label}</Button>
          : <Badge key={item.id} variant="outline" className="whitespace-normal text-caption font-normal text-muted-foreground">{label}</Badge>
      })}
    </div>
    <Dialog open={!!opened} onOpenChange={open => { if (!open) setOpened(null) }}>
      <DialogContent onCloseAutoFocus={event => { event.preventDefault(); trigger.current?.focus() }}>
        <DialogHeader><DialogTitle>{opened?.label} 계산 근거</DialogTitle><DialogDescription>시세 기준 {asOf ?? '미확인'} · 관측값과 조건 충족 여부를 구분해 표시합니다.</DialogDescription></DialogHeader>
        <div className="space-y-4">{opened?.conditions.map(entry => <div key={entry.id} className="space-y-2 rounded-lg bg-muted/40 p-3">
          <p className="text-sm font-medium">{entry.label} · {SCAN_STATUS[entry.status]}</p>
          <dl className="grid grid-cols-2 gap-2 text-sm"><dt>계산 값</dt><dd className="text-right tabular-nums">{evidenceValue(entry.value, 15)}</dd><dt>비교 기준</dt><dd className="text-right tabular-nums">{evidenceValue(entry.reference, 15)}</dd><dt>판정일</dt><dd className="text-right">{entry.date ?? '해당 없음'}</dd></dl>
          {entry.reason && <p className="text-caption text-muted-foreground">{EXCLUSION_LABELS[entry.reason] ?? entry.reason}</p>}
        </div>)}</div>
      </DialogContent>
    </Dialog>
  </>
}
