import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, LoaderCircle, Sparkles, X } from 'lucide-react'
import api from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { Refinement } from '@/components/analysis/types'

/** Mirrors backend `refine.compose_question` so the preview equals what the server would build. */
export function composeQuestion(refinement: Refinement, choices: Record<number, number>, answers: Record<string, number>): string {
  const lines = ['다음 조건을 모두 만족하는 종목을 찾아줘.']
  refinement.conditions.forEach((condition, index) => {
    const pick = choices[index] ?? 0
    lines.push(`- ${pick === 0 ? condition.text : condition.alternatives[pick - 1].text}`)
  })
  for (const clarification of refinement.clarifications) {
    const option = clarification.options[answers[clarification.id] ?? clarification.selected]
    lines.push(`- ${option.text}`)
  }
  return lines.join('\n')
}

function useRefineQuestion() {
  return useMutation({
    mutationFn: async (question: string) => {
      try { return (await api.post<Refinement>('/api/analysis/refine', { question })).data }
      catch (error) {
        const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
        throw new Error(typeof detail === 'string' ? detail : '질문을 다듬지 못했습니다. 잠시 후 다시 시도해 주세요.')
      }
    },
  })
}

const CONFIDENCE: Record<string, string> = { low: '해석 확신 낮음 · 대안 확인', medium: '해석 보통', high: '' }

/** "AI와 다듬기": one model call turns a vague sentence into catalog conditions, alternatives and clarifications. */
export function QuestionRefiner({ question, disabled = false, onApply }: { question: string; disabled?: boolean; onApply: (text: string) => void }) {
  const refine = useRefineQuestion()
  const [result, setResult] = useState<Refinement | null>(null)
  const [choices, setChoices] = useState<Record<number, number>>({})
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const composed = useMemo(() => result ? composeQuestion(result, choices, answers) : '', [result, choices, answers])
  async function start() {
    if (!question.trim() || refine.isPending) return
    try { setResult(await refine.mutateAsync(question)); setChoices({}); setAnswers({}) } catch { /* Inline error below. */ }
  }
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" variant="outline" size="sm" disabled={disabled || refine.isPending || !question.trim()} onClick={() => void start()}>
        {refine.isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Sparkles className="size-4" />}{refine.isPending ? '다듬는 중…' : result ? '다시 다듬기' : 'AI와 다듬기'}
      </Button>
      <span className="text-caption text-muted-foreground">두루뭉술한 표현을 계산 가능한 조건으로 풀고, 시간축·시가총액처럼 정해지지 않은 점을 확인합니다. 누를 때만 모델을 한 번 호출합니다.</span>
    </div>
    {refine.error && <p role="alert" className="text-sm text-destructive">{refine.error.message}</p>}
    {result && <Card aria-label="다듬은 질문">
      <CardHeader className="space-y-1 pb-3">
        <div className="flex items-start justify-between gap-2"><p className="text-sm font-medium">이렇게 이해했습니다</p><Button type="button" variant="ghost" size="icon-sm" aria-label="다듬기 닫기" onClick={() => setResult(null)}><X className="size-4" /></Button></div>
        <p className="text-sm text-muted-foreground">{result.restatement}</p>
      </CardHeader>
      <CardContent className="space-y-5">
        {result.conditions.length > 0 && <section className="space-y-2" aria-label="구체화한 조건">
          <p className="text-caption font-medium text-muted-foreground">계산 조건</p>
          {result.conditions.map((condition, index) => <div key={`${condition.strategy_id ?? 'text'}-${index}`} className="space-y-1 rounded-lg border p-3">
            {condition.alternatives.length > 0 ? <Select value={String(choices[index] ?? 0)} onValueChange={value => setChoices({ ...choices, [index]: Number(value) })}>
              <SelectTrigger aria-label={`${condition.source || condition.text} 해석 선택`} className="h-auto min-h-9 whitespace-normal text-left"><SelectValue /></SelectTrigger>
              <SelectContent>{[condition, ...condition.alternatives].map((option, optionIndex) => <SelectItem key={optionIndex} value={String(optionIndex)}>{option.text}</SelectItem>)}</SelectContent>
            </Select> : <p className="text-sm">{condition.text}</p>}
            <p className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">{condition.source && <span>원문 “{condition.source}”</span>}{CONFIDENCE[condition.confidence] && <Badge variant="outline" className="font-normal text-hypothesis">{CONFIDENCE[condition.confidence]}</Badge>}</p>
          </div>)}
        </section>}
        {result.unsupported.length > 0 && <section className="space-y-1 rounded-lg bg-hypothesis/10 p-3" aria-label="평가할 수 없는 조건">
          <p className="flex items-center gap-1 text-sm font-medium"><AlertTriangle className="size-4" />지금 자료로는 평가할 수 없는 조건</p>
          <ul className="list-disc space-y-1 pl-5 text-sm">{result.unsupported.map((item, index) => <li key={index}>{item.text}<span className="text-muted-foreground"> — {item.reason}</span></li>)}</ul>
          <p className="text-caption text-muted-foreground">이 조건은 검색 문장에서 빠집니다. 후보가 나오면 기업 조사에서 따로 확인하세요.</p>
        </section>}
        {result.clarifications.length > 0 && <section className="space-y-3" aria-label="확인할 점">
          <p className="text-caption font-medium text-muted-foreground">정해지지 않은 점</p>
          {result.clarifications.map(clarification => <div key={clarification.id} className="space-y-1">
            <Label className="text-sm">{clarification.question}</Label>
            <ToggleGroup type="single" variant="outline" size="sm" className="flex-wrap justify-start" value={String(answers[clarification.id] ?? clarification.selected)} onValueChange={value => { if (value) setAnswers({ ...answers, [clarification.id]: Number(value) }) }} aria-label={clarification.question}>
              {clarification.options.map((option, index) => <ToggleGroupItem key={index} value={String(index)} className="h-8 px-3 text-sm">{option.label}</ToggleGroupItem>)}
            </ToggleGroup>
          </div>)}
        </section>}
        <section className="space-y-2" aria-label="다듬은 문장">
          <p className="text-caption font-medium text-muted-foreground">다듬은 문장</p>
          <pre className="whitespace-pre-wrap break-words rounded-lg bg-muted p-3 font-sans text-sm">{composed}</pre>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-caption text-muted-foreground">반영 후에도 문장을 직접 고칠 수 있습니다. 검색 시 이 문장을 다시 해석합니다.</p>
            <Button type="button" size="sm" onClick={() => onApply(composed)}>입력창에 반영</Button>
          </div>
        </section>
      </CardContent>
    </Card>}
  </div>
}
