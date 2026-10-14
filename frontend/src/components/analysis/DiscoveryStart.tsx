import { useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowUpRight, ChartCandlestick, History, PenLine } from 'lucide-react'
import { useRecentCompanySearches } from '@/hooks/useRecentCompanySearches'
import CompanySearchCombobox from '@/components/shared/CompanySearchCombobox'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { STRUCTURE_PRESETS, type StructureParams } from '@/components/structure/ChartStructureCard'
import { ConditionStackBuilder, type StrategySubmission } from '@/components/analysis/ConditionStackBuilder'
import type { Company } from '@/types'

export function DiscoveryStart({ busy, onStart, onDraw }: {
  busy: boolean; onStart: (body: StrategySubmission) => Promise<void>; onDraw: (params: StructureParams) => void
}) {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [company, setCompany] = useState<Pick<Company, 'corp_name' | 'stock_code'> | null>(null)
  const history = useRecentCompanySearches()
  const companyPicker = useRef<HTMLFieldSetElement>(null)
  const selectCompany = (selected: Pick<Company, 'corp_name' | 'stock_code'>) => {
    setCompany(selected)
    history.remember(selected)
  }
  const preset = STRUCTURE_PRESETS.find(preset => preset.id === params.get('draw_preset')) ?? STRUCTURE_PRESETS[0]
  return <div className="space-y-5">
    <Card className="overflow-hidden border-primary/25 bg-primary/5" aria-label="아는 종목 분석">
      <CardHeader className="space-y-3"><div className="flex items-center gap-3"><span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground"><ChartCandlestick className="size-6" aria-hidden="true" /></span><div className="space-y-1"><h2 className="text-section font-semibold">아는 종목 분석</h2><p className="text-sm text-muted-foreground">종목을 정했다면, 차트부터 살펴보세요.</p></div></div></CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-2">
        <fieldset ref={companyPicker} disabled={busy} className="flex min-w-0 flex-wrap items-end gap-3"><legend className="sr-only">분석할 종목 선택</legend>
          <div className="min-w-0 flex-1 basis-64 space-y-2"><p className="text-caption font-medium">분석할 국내 종목</p><CompanySearchCombobox value={company} onSelect={selectCompany} placeholder="종목 이름 또는 코드 검색" className="min-h-11 w-full bg-background" /></div>
          <Button variant="outline" className="min-h-11 bg-background" disabled={!company?.stock_code || busy} onClick={() => { if (company?.stock_code) navigate(`/analyze/${company.stock_code}/summary?scan=1`) }}>기술적 분석 열기<ArrowUpRight className="size-4" /></Button>
        </fieldset>
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-primary/15 bg-background/80 p-3">
          <div className="min-w-0 flex-1 basis-60 space-y-2"><Label htmlFor="discovery-draw-preset" className="flex items-center gap-2"><PenLine className="size-4 text-primary" aria-hidden="true" />차트에 구조 바로 그리기</Label><Select value={preset.id} disabled={busy} onValueChange={value => setParams(previous => { const next = new URLSearchParams(previous); next.set('draw_preset', value); return next }, { replace: true, preventScrollReset: true })}><SelectTrigger id="discovery-draw-preset" className="min-h-11 w-full bg-background"><SelectValue /></SelectTrigger><SelectContent>{STRUCTURE_PRESETS.map(preset => <SelectItem key={preset.id} value={preset.id}>{preset.label}</SelectItem>)}</SelectContent></Select><p className="text-caption text-muted-foreground">{preset.purpose}</p></div>
          <Button className="min-h-11" disabled={!company?.stock_code || busy} onClick={() => { if (company?.stock_code) onDraw({ code: company.stock_code, market: 'kr', ...preset.params }) }}><PenLine className="size-4" />구조 바로 그리기</Button>
        </div>
        <section aria-label="최근 종목 검색" className="min-w-0 space-y-2 border-t border-primary/15 pt-3 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <h3 className="flex items-center gap-1.5 text-caption font-medium"><History className="size-3.5 text-muted-foreground" aria-hidden="true" />최근 검색</h3>
            {history.recent.length > 0 && <Button variant="ghost" size="sm" disabled={busy} aria-label="최근 종목 검색 기록 전체 삭제" className="min-h-11 text-caption text-muted-foreground" onClick={() => { history.clear(); companyPicker.current?.querySelector<HTMLButtonElement>('[role="combobox"]')?.focus() }}>전체 삭제</Button>}
          </div>
          {history.recent.length > 0 ? <ul className="flex min-w-0 flex-wrap gap-2" aria-label="최근 검색한 종목">
            {history.recent.map(recent => <li key={recent.stock_code} className="min-w-0 max-w-full"><Button variant="outline" disabled={busy} aria-pressed={company?.stock_code === recent.stock_code} aria-label={`${recent.corp_name} (${recent.stock_code}) 다시 선택`} title={`${recent.corp_name} (${recent.stock_code})`} className="min-h-11 max-w-full gap-2 bg-background aria-pressed:border-primary aria-pressed:bg-primary/5" onClick={() => selectCompany(recent)}><span className="truncate">{recent.corp_name}</span><span className="shrink-0 text-caption font-normal tabular-nums text-muted-foreground">{recent.stock_code}</span></Button></li>)}
          </ul> : <p className="text-caption text-muted-foreground">검색해 선택한 종목이 여기에 표시됩니다.</p>}
          {!history.stored ? <p role="status" className="text-caption text-muted-foreground">브라우저에 기록을 저장하지 못했습니다. 변경한 기록은 현재 화면에서만 유지됩니다.</p> : history.recent.length > 0 && <p className="text-caption text-muted-foreground">이 브라우저에 최근 8개까지 저장됩니다. 종목을 선택해 분석이나 구조 그리기를 이어가세요.</p>}
        </section>
      </CardContent>
    </Card>
    <ConditionStackBuilder busy={busy} onStart={onStart} />
  </div>
}
