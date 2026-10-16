import { useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/shared/ErrorState'
import { DetailLink } from '@/components/shared/DetailNavigation'
import { useGroupReasons, useStartReason } from '@/hooks/useGroups'
import type { QuestionVerdict, StockGroupDetail } from '@/types'

const VERDICT: Record<string, { label: string; cls: string }> = {
  leaning_yes: { label: '지지', cls: 'text-up border-up/40' },
  leaning_no: { label: '약화', cls: 'text-down border-down/40' },
  mixed: { label: '엇갈림', cls: 'text-muted-foreground' },
  unknown: { label: '관측 전', cls: 'text-muted-foreground' },
}
const V = (v: QuestionVerdict) => VERDICT[v ?? 'unknown'] ?? VERDICT.unknown

/**
 * 관심 종목 이유 감시(D-227, portfolio-intelligence §6) — "왜 보고 있나 / 무엇이 오면 움직이나"를 핵심질문 추적기로
 * 매일 07:40 판정하고, 판정이 어느 쪽으로든 기울면 텔레그램으로 알린다. 원문은 로컬 DB에만.
 */
export function WatchReasonsCard({ detail }: { detail: StockGroupDetail }) {
  const reasons = useGroupReasons(detail.id)
  const start = useStartReason(detail.id)
  const [open, setOpen] = useState<string | null>(null)
  const [why, setWhy] = useState('')
  const [trigger, setTrigger] = useState('')

  function submit(code: string) {
    if (why.trim().length < 5 || start.isPending) return
    start.mutate({ stock_code: code, why: why.trim(), trigger: trigger.trim() }, {
      onSuccess: () => { setOpen(null); setWhy(''); setTrigger(''); toast.success('감시를 시작했습니다. 매일 아침 판정하고, 기울면 텔레그램으로 알립니다.') },
      onError: e => toast.error(e instanceof Error ? e.message : '감시를 시작하지 못했습니다.'),
    })
  }

  return <Card>
    <CardHeader><CardTitle>관심 이유</CardTitle>
      <CardDescription>종목마다 왜 보고 있는지와 무엇이 오면 움직일지를 적으세요. 매일 아침 판정해, 이유가 맞아가거나 약해지면 텔레그램으로 알립니다.</CardDescription></CardHeader>
    <CardContent>
      {reasons.isPending ? <Skeleton className="h-32 w-full" />
        : reasons.isError ? <ErrorState message="관심 이유를 불러오지 못했습니다." onRetry={() => void reasons.refetch()} />
        : !detail.members.length ? <p className="text-sm text-muted-foreground">묶음에 종목을 먼저 추가하세요.</p>
        : <ul className="divide-y" aria-label="종목별 관심 이유">{detail.members.map(m => {
          const r = reasons.data[m.stock_code]
          return <li key={m.stock_code} className="space-y-2 py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <span className="font-medium">{m.name}</span>
              {r ? <span className="flex flex-wrap items-center gap-1.5 text-caption">
                  <span className="text-muted-foreground">선행</span><Badge variant="outline" className={V(r.lead).cls}>{V(r.lead).label}</Badge>
                  <span className="text-muted-foreground">확정</span><Badge variant="outline" className={V(r.confirm).cls}>{V(r.confirm).label}</Badge>
                  <DetailLink to={`/question/${r.id}`} className="ml-1 text-primary hover:underline">상세 →</DetailLink></span>
                : open !== m.stock_code && <Button variant="outline" size="sm" onClick={() => { setOpen(m.stock_code); setWhy(m.thesis ?? ''); setTrigger('') }}>이유 적기</Button>}
            </div>
            {r && <>
              <p className="text-sm text-muted-foreground">{r.text}</p>
              {r.signals.length > 0 && <p className="text-caption">{r.signals.join(' · ')}</p>}
              {r.summary && <p className="text-caption text-muted-foreground">{r.summary}</p>}
            </>}
            {!r && open === m.stock_code && <form className="space-y-2" onSubmit={e => { e.preventDefault(); submit(m.stock_code) }}>
              <Label htmlFor={`why-${m.stock_code}`}>왜 보고 있나</Label>
              <Textarea id={`why-${m.stock_code}`} value={why} maxLength={4000} disabled={start.isPending} className="min-h-16" onChange={e => setWhy(e.target.value)} placeholder="예: 고객사 증설이 본격화되면 장비 수주가 늘어난다" />
              <Label htmlFor={`trigger-${m.stock_code}`}>무엇이 오면 움직이나 (선택)</Label>
              <Textarea id={`trigger-${m.stock_code}`} value={trigger} maxLength={1000} disabled={start.isPending} className="min-h-12" onChange={e => setTrigger(e.target.value)} placeholder="예: 대형 수주 공시가 나오면 매수 검토, 증설이 미뤄지면 접는다" />
              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" size="sm" disabled={start.isPending || why.trim().length < 5}>{start.isPending && <LoaderCircle className="size-4 animate-spin" />}{start.isPending ? '질문으로 나누는 중(1~3분)…' : '감시 시작'}</Button>
                <Button type="button" variant="ghost" size="sm" disabled={start.isPending} onClick={() => setOpen(null)}>취소</Button>
              </div>
            </form>}
          </li>
        })}</ul>}
    </CardContent>
  </Card>
}
