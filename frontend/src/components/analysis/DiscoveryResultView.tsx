import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, ChevronRight } from 'lucide-react'
import { InfoTip } from '@/components/regimes/Section'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { evidenceValue, strategyCheck } from '@/components/analysis/strategyEvidence'
import { cn } from '@/lib/utils'
import { formatKrw, formatNumber } from '@/utils/format'
import type { AnalysisCandidate, AnalysisResult, AnalysisSpec } from '@/components/analysis/types'

/**
 * 종목 발견 결과 화면(전체 폭, 시안 Discover-Results · ia-redesign §4.19·§4.24, D-300) — 조건 칩 띠 · 조건별 통과 수 · 후보 표.
 * 근거 창(차트·조건별 계산 값·행동 버튼)은 AnalysisResults의 CandidateChart를 그대로 쓴다. 모바일은 근거 창 없이 종목을 누르면 도시에로(§4.32).
 */

const MARKET: Record<AnalysisSpec['market'], string> = { all: '국내 전체', KOSPI: 'KOSPI', KOSDAQ: 'KOSDAQ' }

/** 조건 이름 — 실행에 저장된 정의 → 카탈로그 이름표 → id */
export function conditionLabel(id: string, result: AnalysisResult | null | undefined, labels: Record<string, string>): string {
  return result?.strategy_definitions?.find(d => d.id === id)?.label ?? labels[id] ?? id
}

/** 조건 칩 띠 — 검색 범위 · 조건 칩 · (오른쪽) 행동 */
export function ConditionStrip({ spec, result, labels, status, actions }: {
  spec: AnalysisSpec; result: AnalysisResult | null; labels: Record<string, string>; status?: string | null; actions: ReactNode
}) {
  const scope = spec.universe_codes?.length ? `지정 종목 ${formatNumber(spec.universe_codes.length)}` : MARKET[spec.market] ?? spec.market
  return <div aria-label="검색 조건" className="flex flex-wrap items-center gap-2 border bg-card px-3 py-2.5">
    {status && <Badge variant="outline">{status}</Badge>}
    <span className="text-caption text-muted-foreground">{scope} · 모두 만족</span>
    {(spec.strategy_conditions ?? []).map(c => <Badge key={c.strategy_id} variant="outline" className="font-medium text-muted-foreground">{conditionLabel(c.strategy_id, result, labels)}</Badge>)}
    <span className="ml-auto flex flex-wrap items-center gap-1.5">{actions}</span>
  </div>
}

/** 조건별 통과 수와 '빼면 +n종목'(D-223) — 가장 큰 '빼면'이 병목(경고 색). 순위 조건은 서버가 세지 않아 칸이 없다 */
export function ConditionFunnel({ result, labels }: { result: AnalysisResult; labels: Record<string, string> }) {
  const funnel = result.condition_funnel
  if (!funnel?.conditions.length) return null
  const order = (result.spec.strategy_conditions ?? []).map(c => c.strategy_id)
  const cells = [...funnel.conditions].sort((a, b) => order.indexOf(a.strategy_id) - order.indexOf(b.strategy_id))
  const worst = cells.length > 1 ? cells.reduce((m, c) => (c.sole_blocker > m.sole_blocker ? c : m)) : null
  return <div aria-label="조건별 통과 수" style={{ '--funnel-cols': `repeat(${cells.length}, minmax(0,1fr)) minmax(0,0.8fr)` } as CSSProperties}
    className="grid grid-cols-2 border bg-card md:[grid-template-columns:var(--funnel-cols)]">
    {cells.map(c => <div key={c.strategy_id} className="flex min-w-0 flex-col gap-1 px-3 py-2.5">
      <span className="truncate text-caption text-muted-foreground">{order.indexOf(c.strategy_id) + 1}. {conditionLabel(c.strategy_id, result, labels)}</span>
      <span className="font-mono text-lg tabular-nums">{formatNumber(c.passed)}<span className="text-caption text-muted-foreground"> / {formatNumber(funnel.evaluated)}</span></span>
      <span className={cn('text-caption', worst?.strategy_id === c.strategy_id && c.sole_blocker > 0 ? 'text-chart-warning' : 'text-muted-foreground')}>
        {c.sole_blocker > 0 ? `빼면 +${formatNumber(c.sole_blocker)}종목` : '빼도 그대로'}</span>
    </div>)}
    <div className="flex min-w-0 flex-col gap-1 bg-muted/60 px-3 py-2.5">
      <span className="text-caption text-muted-foreground">모두 만족</span>
      <span className="font-mono text-lg tabular-nums">{formatNumber(result.counts.matched)}</span>
    </div>
  </div>
}

/** 후보 표 칸 값 — 순위 조건은 n위, 값이 있으면 계산 값, 없으면 판정일(MM/DD) */
export function conditionCell(item: AnalysisCandidate, id: string): string {
  const check = strategyCheck(item.checks[id])
  if (check.rank != null) return `${formatNumber(check.rank)}위`
  if (check.value != null && typeof check.value !== 'boolean') return evidenceValue(check.value, 2)
  if (check.date) return check.date.slice(5).replace('-', '/')
  return '-'
}

export function WideCandidateTable({ result, items, selected, onSelect, compared, onCompare, ascending, onSort, labels }: {
  result: AnalysisResult; items: AnalysisCandidate[]; selected: string; onSelect: (code: string) => void
  compared: string[]; onCompare: (code: string) => void; ascending: boolean; onSort: () => void; labels: Record<string, string>
}) {
  const ids = (result.spec.strategy_conditions ?? []).map(c => c.strategy_id)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {   // 고른 종목이 표 밖이면 보이게(다시 열었을 때)
    box.current?.querySelector<HTMLElement>('[data-state="selected"]')?.scrollIntoView({ block: 'nearest' })
  }, [])
  const SortIcon = ascending ? ArrowUp : ArrowDown
  return <div ref={box} className="max-h-[min(70dvh,48rem)] overflow-auto">
    <Table aria-label="후보 종목 목록">
      <TableHeader className="sticky top-0 z-10 bg-card"><TableRow>
        <TableHead>종목</TableHead>
        <TableHead className="text-right"><Button variant="ghost" size="sm" className="h-8 gap-1 px-1" aria-label={`시가총액 정렬 · ${ascending ? '작은 순' : '큰 순'}`} onClick={onSort}>시가총액<SortIcon className="size-3.5" aria-hidden="true" /></Button></TableHead>
        {ids.map(id => <TableHead key={id} title={conditionLabel(id, result, labels)} className="h-auto min-w-[4.5rem] max-w-28 whitespace-normal py-1.5 text-right text-caption leading-tight">{conditionLabel(id, result, labels)}</TableHead>)}
        <TableHead className="w-10 text-center">비교</TableHead>
      </TableRow></TableHeader>
      <TableBody>{items.map(item => <TableRow key={item.code} data-state={item.code === selected ? 'selected' : undefined} className="cursor-pointer" onClick={() => onSelect(item.code)}>
        <TableCell className="max-w-[12rem]">
          <span className="flex min-w-0 items-center gap-1.5">
            <button type="button" id={`discovery-candidate-${item.code}`} aria-pressed={item.code === selected} aria-label={`${item.name} 차트와 근거 보기`} onClick={e => { e.stopPropagation(); onSelect(item.code) }} className="min-w-0 truncate text-left font-semibold">{item.name}</button>
            <span className="shrink-0 font-mono text-caption text-muted-foreground">{item.code}</span>
            {item.status === 'provisional' && <Badge variant="outline" title="잠정 후보 — 미검증 항목이 있습니다" className="h-4 shrink-0 px-1 text-[10px] font-normal text-hypothesis">잠정</Badge>}
          </span>
        </TableCell>
        <TableCell className="text-right tabular-nums">{formatKrw(item.market_cap)}</TableCell>
        {ids.map(id => <TableCell key={id} className="text-right font-mono tabular-nums">{conditionCell(item, id)}</TableCell>)}
        <TableCell className="text-center" onClick={e => e.stopPropagation()}>
          <Checkbox aria-label={`${item.name} 비교 선택`} checked={compared.includes(item.code)} disabled={compared.length >= 3 && !compared.includes(item.code)} onCheckedChange={() => onCompare(item.code)} />
        </TableCell>
      </TableRow>)}</TableBody>
    </Table>
  </div>
}

/** 모바일 후보 목록 — 근거 창 없이 종목을 누르면 도시에(§4.32) */
export function MobileCandidateList({ result, items, labels }: { result: AnalysisResult; items: AnalysisCandidate[]; labels: Record<string, string> }) {
  const ids = (result.spec.strategy_conditions ?? []).map(c => c.strategy_id).slice(0, 2)
  return <ul aria-label="후보 종목 목록" className="divide-y border-y">
    {items.map(item => <li key={item.code}>
      <Link to={`/analyze/${item.code}/summary`} className="flex items-center gap-3 py-3">
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">{item.name}<span className="ml-1.5 font-mono text-caption font-normal text-muted-foreground">{item.code}</span></span>
          <span className="block truncate text-caption text-muted-foreground">{ids.map(id => `${conditionLabel(id, result, labels)} ${conditionCell(item, id)}`).join(' · ')}</span>
        </span>
        <span className="shrink-0 text-right text-sm tabular-nums">{formatKrw(item.market_cap)}</span>
        <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>
    </li>)}
  </ul>
}

/** '후보 n개' 머리 — 기준일·대상·평가·미평가는 ⓘ로 */
export function CandidateHeading({ result }: { result: AnalysisResult }) {
  const c = result.counts
  const inconclusive = c.matched === 0 && c.excluded > 0
  return <h2 className="flex items-center gap-1 text-section font-semibold">
    {inconclusive ? '통과 확인 0개 · 일부 미평가' : `후보 ${formatNumber(c.matched)}개`}
    <InfoTip label="후보 수 기준">{result.as_of} 기준 · 대상 {formatNumber(c.universe)} · 평가 {formatNumber(c.evaluated)} · 조건 탈락 {formatNumber(Math.max(0, c.evaluated - c.matched))}{c.excluded > 0 && ` · 미평가 ${formatNumber(c.excluded)}(자료 부족 또는 계산 오류)`}</InfoTip>
  </h2>
}
