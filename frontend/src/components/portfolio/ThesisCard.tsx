import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { DetailLink } from '@/components/shared/DetailNavigation'
import { JudgingPausedNotice } from '@/components/shared/JudgingPausedNotice'
import { usePortfolioTheses, useStartThesis } from '@/hooks/usePortfolio'
import type { QuestionVerdict } from '@/types'

const VERDICT: Record<string, { label: string; cls: string }> = {
  leaning_yes: { label: '지지', cls: 'text-up border-up/40' },
  leaning_no: { label: '약화', cls: 'text-down border-down/40' },
  mixed: { label: '엇갈림', cls: 'text-muted-foreground' },
  unknown: { label: '관측 전', cls: 'text-muted-foreground' },
}
const V = (v: QuestionVerdict) => VERDICT[v ?? 'unknown'] ?? VERDICT.unknown

/** 보유 논지·반증 감시 — 기존 핵심질문 추적기로 매일 판정(portfolio-intelligence §2). */
export function ThesisCard({ code, name }: { code: string; name: string }) {
  const theses = usePortfolioTheses()
  const start = useStartThesis()
  const [why, setWhy] = useState('')
  const [falsifier, setFalsifier] = useState('')
  const t = theses.data?.[code]
  return <Card>
    <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
      <div className="space-y-1"><CardTitle>보유 논지</CardTitle>
        <CardDescription>산 이유가 아직 유효한지 매일 아침 판정합니다. 나빠지면 텔레그램으로 알립니다.</CardDescription></div>
      {t && <DetailLink to={`/question/${t.id}`} className="text-sm text-primary hover:underline">질문 상세 →</DetailLink>}
    </CardHeader>
    <CardContent className="space-y-3">
      {theses.isPending ? <Skeleton className="h-24 w-full" />
        : theses.isError ? <Button variant="outline" size="sm" onClick={() => void theses.refetch()}>다시 불러오기</Button>
        : t ? <>
          {!t.judging && <JudgingPausedNotice judgedAt={t.judged_at} />}
          <p className="text-sm">{t.text}</p>
          <div className="flex flex-wrap items-center gap-2 text-caption">
            <span className="text-muted-foreground">선행 신호</span><Badge variant="outline" className={`text-caption ${V(t.lead).cls}`}>{V(t.lead).label}</Badge>
            <span className="text-muted-foreground">확정 지표</span><Badge variant="outline" className={`text-caption ${V(t.confirm).cls}`}>{V(t.confirm).label}</Badge>
          </div>
          {t.warnings.length > 0 && <div role="alert" className="flex gap-2 rounded-lg border border-down/30 p-3 text-sm">
            <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-down" /><ul>{t.warnings.map(w => <li key={w}>{w}</li>)}</ul></div>}
          {t.summary && <p className="text-sm text-muted-foreground">{t.summary}</p>}
          <ul className="divide-y">{t.sub_questions.map(s => <li key={s.text} className="flex items-start gap-3 py-2 text-sm">
            <Badge variant="outline" className={`mt-0.5 shrink-0 text-caption ${V(s.verdict).cls}`}>{V(s.verdict).label}</Badge>
            <div className="min-w-0"><p>{s.text}</p>{s.falsifier && <p className="text-caption text-muted-foreground">틀린 조건: {s.falsifier}</p>}</div>
          </li>)}</ul>
          <p className="text-caption text-muted-foreground">국내 종목은 문서 논조와 미국 관련 기업 실적발표 지표로 판정합니다. 국내 시세·공시 지표는 다음 단계입니다.</p>
        </>
        : <form className="space-y-3" onSubmit={e => {
            e.preventDefault()
            start.mutate({ stock_code: code, why, falsifier }, {
              onSuccess: () => { toast.success('논지 감시를 시작했습니다.'); setWhy(''); setFalsifier('') },
              onError: err => toast.error(err.message),
            })
          }}>
          <div className="space-y-1.5"><Label htmlFor={`why-${code}`}>왜 샀나</Label>
            <Textarea id={`why-${code}`} value={why} onChange={e => setWhy(e.target.value)} rows={2} placeholder={`예: ${name}의 HBM 장비 수주가 하반기에 늘어난다`} /></div>
          <div className="space-y-1.5"><Label htmlFor={`fal-${code}`}>무엇이면 틀린 건가</Label>
            <Textarea id={`fal-${code}`} value={falsifier} onChange={e => setFalsifier(e.target.value)} rows={2} placeholder="예: 고객사 메모리 투자 계획이 줄어든다" /></div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" size="sm" disabled={why.trim().length < 5 || start.isPending}>{start.isPending ? '논지를 나누는 중…' : '감시 시작'}</Button>
            <span className="text-caption text-muted-foreground">{start.isPending ? 'AI가 하위 질문·틀린 조건·관측 지표로 나누고 있습니다(1~3분).' : 'AI 1회 사용(분해). 이후 매일 판정은 계산만 합니다.'}</span>
          </div>
        </form>}
    </CardContent>
  </Card>
}
