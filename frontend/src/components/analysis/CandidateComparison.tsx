import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { checkValue, evidenceValue, strategyCheck } from '@/components/analysis/strategyEvidence'
import { formatKrw } from '@/utils/format'
import type { AnalysisCandidate, AnalysisResult } from '@/components/analysis/types'

export function candidateAnalysisUrl(runId: string, code: string, compared: string[], ascending: boolean, technical = true) {
  const params = new URLSearchParams({ source_run: runId, scan_at: technical ? 'discovery' : 'latest', source_sort: ascending ? 'cap_asc' : 'cap_desc' })
  if (technical) params.set('scan', '1')
  if (compared.length) params.set('source_compare', compared.join(','))
  return `/analyze/${code}/summary?${params}`
}

export function CandidateComparison({ runId, result, items, ascending, onClear }: {
  runId: string; result: AnalysisResult; items: AnalysisCandidate[]; ascending: boolean; onClear: () => void
}) {
  const ids = [...new Set(items.flatMap(item => Object.keys(item.checks ?? {})))]
  const codes = items.map(item => item.code)
  return <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-3" aria-label="후보 비교 선택">
    <div className="space-y-1"><p className="text-sm font-medium" role="status">비교 {items.length}/3개{items.length > 0 && ` · ${items.map(item => item.name).join(' · ')}`}</p><p className="text-caption text-muted-foreground">목록의 비교 선택란에서 2~3개를 고르세요. 저장된 같은 시점의 판정을 비교합니다.</p></div>
    <div className="flex gap-2">{items.length > 0 && <Button variant="ghost" onClick={onClear}>선택 해제</Button>}
      <Dialog><DialogTrigger asChild><Button variant="outline" disabled={items.length < 2}>선택 후보 비교</Button></DialogTrigger>
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-5xl"><DialogHeader><DialogTitle>후보 비교 · {result.as_of}</DialogTitle><DialogDescription>동일한 검색 실행에 저장된 조건별 판정입니다. 계산 값과 비교 기준의 단위는 조건마다 다릅니다.</DialogDescription></DialogHeader>
          <Table aria-label="같은 기준일의 후보 비교"><TableHeader><TableRow><TableHead className="min-w-28">비교 항목</TableHead>{items.map(item => <TableHead key={item.code} className="min-w-44 whitespace-normal"><span className="block font-semibold text-foreground">{item.name}</span><span className="block text-caption">{item.code}</span></TableHead>)}</TableRow></TableHeader>
            <TableBody>
              <TableRow><TableHead scope="row">시세 기준일</TableHead>{items.map(item => <TableCell key={item.code}>{result.as_of}</TableCell>)}</TableRow>
              <TableRow><TableHead scope="row">시가총액</TableHead>{items.map(item => <TableCell key={item.code}>{formatKrw(item.market_cap)}</TableCell>)}</TableRow>
              <TableRow><TableHead scope="row">후보 상태</TableHead>{items.map(item => <TableCell key={item.code}>{item.status === 'provisional' ? '잠정 · 미검증 항목 확인' : '통과 후보'}</TableCell>)}</TableRow>
              {ids.map(id => <TableRow key={id}><TableHead scope="row" className="whitespace-normal align-top">{result.strategy_definitions?.find(d => d.id === id)?.label ?? items.map(item => strategyCheck(item.checks[id]).label).find(Boolean) ?? ({ market_cap: '시가총액 조건', expression: '복합 조건식', ma_hold: '이동평균 유지', high52: '52주 신고가', neckline_breakout: '넥라인 돌파', coverage: '데이터 범위', price_adjustment: '수정주가', calendar: '거래일 달력', event_order: '사건 순서', pattern: '패턴' } as Record<string, string>)[id] ?? id}</TableHead>{items.map(item => {
                const value = item.checks[id]
                const check = strategyCheck(value)
                return <TableCell key={item.code} className="space-y-1 whitespace-normal align-top"><p className="text-sm">{checkValue(value)}</p><div className="space-y-1 text-caption text-muted-foreground"><div>계산 값: <span className="tabular-nums">{evidenceValue(check.value, 8)}</span></div><div>비교 기준: <span className="tabular-nums">{evidenceValue(check.reference, 8)}</span></div><div>판정일: {check.date ?? '—'}</div>{check.rank != null && <div>순위: {check.rank}위</div>}</div>{check.estimated && <p className="text-caption text-muted-foreground">일봉 기반 추정</p>}</TableCell>
              })}</TableRow>)}
              <TableRow><TableHead scope="row">상세 확인</TableHead>{items.map(item => <TableCell key={item.code}><Button asChild variant="outline" size="sm"><Link to={candidateAnalysisUrl(runId, item.code, codes, ascending)}>기술적 분석 열기<span className="sr-only"> · {item.name}</span></Link></Button></TableCell>)}</TableRow>
            </TableBody>
          </Table>
          <p className="text-caption text-muted-foreground">‘—’는 이 실행에 해당 값이 저장되지 않았다는 뜻입니다. 현재 시세 변화나 거래대금은 이 표에서 추정하지 않습니다.</p>
          {!!result.unsupported_conditions?.length && <p className="text-sm text-hypothesis">평가하지 못한 요청 조건: {result.unsupported_conditions.join(' · ')}</p>}
        </DialogContent>
      </Dialog>
    </div>
  </div>
}
