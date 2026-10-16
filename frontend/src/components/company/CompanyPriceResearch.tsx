import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import CandlestickChart from '@/components/charts/CandlestickChart'
import { Activity, PenLine } from 'lucide-react'
import { TechnicalScan, scanToChart, useTechnicalScan } from './TechnicalScan'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { CompanyEvidence } from './CompanyEvidence'
import { shiftDay, validDay } from '@/utils/companyResearch'
import type { StockPriceItem } from '@/types'
import { DiscoveryTechnicalContext } from '@/components/company/DiscoveryTechnicalContext'

export function CompanyPriceResearch({
  company,
  prices,
  loading,
  error,
  retry,
  market = 'kr',
  overview,
  compact = false,
}: {
  company: string
  prices: StockPriceItem[]
  loading: boolean
  error: boolean
  retry: () => void
  market?: 'kr' | 'us'
  overview?: ReactNode
  compact?: boolean
}) {
  const [sp, setSp] = useSearchParams()
  const scanOpen = sp.get('scan') === '1'
  const scanWithin = [1, 3, 5, 10, 20].includes(Number(sp.get('scan_within'))) ? Number(sp.get('scan_within')) : 5
  const scanOnChart = sp.get('scan_chart') !== '0'
  const sourceRun = market === 'kr' ? sp.get('source_run') : null
  const original = !!sourceRun && sp.get('scan_at') !== 'latest'
  const scanAnchor = useRef<HTMLDivElement>(null)
  const [notice, setNotice] = useState('')
  const months = [3, 12, 60].includes(Number(sp.get('months')))
    ? Number(sp.get('months'))
    : 12
  const candles = useMemo(
    () =>
      prices
        .filter(
          (p) =>
            p.open != null &&
            p.high != null &&
            p.low != null &&
            p.close != null,
        )
        .map((p) => ({
          time:
            p.trade_date.length === 8
              ? `${p.trade_date.slice(0, 4)}-${p.trade_date.slice(4, 6)}-${p.trade_date.slice(6)}`
              : p.trade_date,
          open: p.open!,
          high: p.high!,
          low: p.low!,
          close: p.close!,
        }))
        .sort((a, b) => a.time.localeCompare(b.time)),
    [prices],
  )
  const dates = useMemo(() => candles.map((p) => p.time), [candles])
  const requested = sp.get('date') || ''
  const selected =
    sp.get('mode') === 'research' && dates.includes(requested) ? requested : ''
  const days = [1, 7, 30, 90].includes(Number(sp.get('days')))
    ? Number(sp.get('days'))
    : 30
  const custom = sp.get('from') || ''
  const start = selected
    ? validDay(custom) && custom <= selected
      ? custom
      : shiftDay(selected, 1 - days)
    : undefined
  const cutoff = sp.get('cutoff') === 'close' ? 'close' : 'end'
  const after = sp.get('after') === '1'
  const latest = dates.at(-1)
  // The scan endpoint only evaluates the latest stored rows. Never mix it into a historical selection.
  const historical = sp.get('mode') === 'research' && !!requested && requested !== latest
  const scanEnabled = scanOpen && !original && !historical && !loading && !error && !!latest
  const scan = useTechnicalScan(company, market, scanWithin, scanEnabled)
  useEffect(() => {
    if (scanOpen) scanAnchor.current?.scrollIntoView({ block: 'start' })
  }, [company, scanOpen, original, scanEnabled])
  const sameDate = scan.data?.as_of === latest
  const scanChart = useMemo(() => scanToChart(scanEnabled && scanOnChart && sameDate ? scan.data : undefined), [scan.data, scanEnabled, scanOnChart, sameDate])
  const oldest = latest ? shiftDay(latest, -months * 31) : ''
  // Keep the same data reference while moving within the displayed interval: do not reset zoom.
  const chartStart = selected && selected < oldest ? dates[0] : oldest
  const chartData = useMemo(
    () => candles.filter((p) => p.time >= chartStart),
    [candles, chartStart],
  )
  const volumes = useMemo(
    () =>
      prices
        .filter((p) => p.volume != null && p.close != null && p.open != null)
        .map((p) => ({
          time:
            p.trade_date.length === 8
              ? `${p.trade_date.slice(0, 4)}-${p.trade_date.slice(4, 6)}-${p.trade_date.slice(6)}`
              : p.trade_date,
          value: p.volume!,
          color: p.close! >= p.open! ? '#ef444480' : '#3b82f680',
        }))
        .filter((p) => p.time >= chartStart)
        .sort((a, b) => a.time.localeCompare(b.time)),
    [prices, chartStart],
  )
  const choose = (day: string) => {
    if (!validDay(day) || day < dates[0] || day > dates.at(-1)!) {
      setNotice('보유한 주가 기간 안의 날짜를 선택해 주세요.')
      return
    }
    const actual = dates.filter((d) => d <= day).at(-1)!
    setNotice(
      actual === day
        ? ''
        : `휴장일은 직전 보유 거래일 ${actual}로 이동했습니다.`,
    )
    setSp(
      (prev) => {
        const n = new URLSearchParams(prev)
        n.set('mode', 'research')
        n.set('date', actual)
        n.delete('page')
        if ((n.get('from') || '') > actual) n.delete('from')
        return n
      },
      { replace: !!selected },
    )
  }
  const update = (key: string, value: string) =>
    setSp(
      (prev) => {
        const n = new URLSearchParams(prev)
        n.set(key, value)
        n.delete('page')
        if (key === 'days') n.delete('from')
        return n
      },
      { replace: true },
    )
  const setScanOpen = (open: boolean) => setSp(previous => {
    const next = new URLSearchParams(previous)
    if (open) next.set('scan', '1')
    else next.delete('scan')
    return next
  }, { replace: true, preventScrollReset: true })
  const viewCurrent = () => setSp(previous => {
    const next = new URLSearchParams(previous)
    next.set('scan', '1')
    next.set('scan_at', 'latest')
    for (const key of ['mode', 'date', 'days', 'from', 'cutoff', 'after', 'page']) next.delete(key)
    return next
  }, { replace: true })
  const current = candles.find((p) => p.time === selected) || candles.at(-1)
  const fieldClass = 'rounded-md border bg-background px-3 py-2 text-sm'
  const priceChart = <>
    {loading ? (
      <p className="flex h-80 items-center justify-center text-muted-foreground">
        주가를 불러오는 중입니다.
      </p>
    ) : error ? (
      <div role="alert">
        <p>주가를 불러오지 못했습니다.</p>
        <Button onClick={retry}>다시 시도</Button>
      </div>
    ) : candles.length ? (
      <CandlestickChart
        data={chartData}
        volumeData={volumes}
        height={compact && !selected && !scanEnabled ? 160 : 360}
        formatValue={value => market === 'us' ? `$${value.toFixed(2)}` : value.toLocaleString('ko-KR')}
        selectedTime={selected}
        selectionStart={start}
        onMarkerClick={choose}
        markers={scanChart.markers}
        overlays={scanChart.overlays}
      />
    ) : (
      <p className="py-20 text-center text-muted-foreground">
        보유한 주가 데이터가 없습니다.
      </p>
    )}
    <p className="text-caption text-muted-foreground">
      캔들을 클릭하면 해당 날짜 이전 자료를 탐색합니다. 휠·드래그로
      차트를 확대·이동할 수 있습니다.
    </p>
  </>
  return (
    <>
      {sourceRun && <div ref={scanAnchor} className="mb-4 scroll-mt-4"><DiscoveryTechnicalContext runId={sourceRun} code={company} original={original} latest={latest} onView={showOriginal => { if (showOriginal) update('scan_at', 'discovery'); else viewCurrent() }} /></div>}
      {!original && <div className="company-research-host">
        <div
          className={selected ? 'company-research-grid' : ''}
          data-testid="company-research"
          data-mode={selected ? 'research' : 'overview'}
        >
          <div className={selected ? 'company-research-chart' : ''}>
            <Card>
              <CardContent className={compact && !selected ? 'space-y-2 pt-4' : 'space-y-4 pt-5'}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className={compact && !selected ? 'text-sm font-medium' : 'text-section font-semibold'}>
                      가격과 거래량
                    </h2>
                    {current && (
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        {market === 'us' ? '$' : ''}
                        {current.close.toLocaleString()}
                        {market === 'kr' ? '원' : ''}
                        <span className="ml-2 text-caption font-normal text-muted-foreground">
                          {selected ? '선택일' : '최근 보유일'} {current.time}{' '}
                          종가
                        </span>
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant={scanOpen ? 'secondary' : 'outline'} size="sm" className="min-h-11" aria-pressed={scanOpen} onClick={() => setScanOpen(!scanOpen)}><Activity className="size-4" />기술적 분석</Button>
                    {!historical && <Button variant={scanOpen && sp.get('scan_view') === 'structure' ? 'secondary' : 'outline'} size="sm" className="min-h-11" disabled={!latest || loading || error} onClick={() => setSp(previous => { const next = new URLSearchParams(previous); next.set('scan', '1'); next.set('scan_view', 'structure'); return next }, { replace: true, preventScrollReset: true })}><PenLine className="size-4" />구조 그리기</Button>}
                  </div>
                  {selected && (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setNotice('')
                        setSp((prev) => {
                          const n = new URLSearchParams(prev)
                          ;[
                            'mode',
                            'date',
                            'days',
                            'from',
                            'cutoff',
                            'after',
                            'source',
                            'q',
                            'page',
                          ].forEach((k) => n.delete(k))
                          return n
                        })
                      }}
                    >
                      ← 개요로 돌아가기
                    </Button>
                  )}
                </div>
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div className="flex gap-1" aria-label="차트 표시 기간">
                    {[3, 12, 60].map((m) => (
                      <Button
                        key={m}
                        size="sm"
                        variant={months === m ? 'default' : 'ghost'}
                        aria-pressed={months === m}
                        onClick={() => update('months', String(m))}
                      >
                        {m === 3 ? '3개월' : m === 12 ? '1년' : '5년'}
                      </Button>
                    ))}
                  </div>
                  <label className="text-caption">
                    {selected ? '선택 거래일' : '궁금한 날짜 선택'}
                    <Input
                      aria-label="선택 거래일"
                      type="date"
                      className="mt-1 w-auto"
                      min={dates[0]}
                      max={latest}
                      value={selected}
                      disabled={!dates.length}
                      onChange={(e) => {
                        if (e.target.value) choose(e.target.value)
                      }}
                    />
                  </label>
                </div>
                {!scanEnabled && priceChart}
                {scanOpen && <div ref={sourceRun ? undefined : scanAnchor} className="scroll-mt-4">
                  {historical ? <section aria-label="선택일 기술적 분석" className="space-y-3 rounded-xl border p-4">
                    <h3 className="text-sm font-semibold">{requested} 기술적 분석 미지원</h3>
                    <p className="text-sm text-muted-foreground">선택한 날짜의 전체 기술적 분석은 제공하지 않습니다. 이 화면의 차트에는 최신 신호를 표시하지 않습니다.</p>
                    <Button variant="outline" size="sm" onClick={viewCurrent}>현재 기술적 분석 보기{latest ? ` · ${latest}` : ''}</Button>
                    <Button variant="ghost" size="sm" onClick={() => setScanOpen(false)}>기술적 분석 닫기</Button>
                  </section> : scanEnabled ? <TechnicalScan key={company} chart={priceChart} code={company} market={market} within={scanWithin} onWithin={value => update('scan_within', String(value))} onChart={scanOnChart} onToggleChart={value => update('scan_chart', value ? '1' : '0')} onClose={() => setScanOpen(false)} /> : <p className="text-sm text-muted-foreground">가격 자료를 확인한 뒤 기술적 분석을 표시합니다.</p>}
                  {scanEnabled && scan.data && !sameDate && <p role="status" className="mt-2 text-caption text-muted-foreground">가격 차트({latest})와 분석({scan.data.as_of ?? '미확인'})의 시세 기준일이 달라 신호를 차트에 겹쳐 표시하지 않습니다.</p>}
                </div>}
                {(notice || (requested && !selected && !loading)) && (
                  <p role="status" className="text-sm text-primary">
                    {notice ||
                      'URL의 날짜에 해당하는 주가를 확보하지 못했습니다. 다른 날짜를 선택해 주세요.'}
                  </p>
                )}
                {selected && (
                  <div className="space-y-4 border-t pt-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant="outline"
                        disabled={selected === dates[0]}
                        onClick={() =>
                          choose(dates[dates.indexOf(selected) - 1])
                        }
                      >
                        ← 이전 거래일
                      </Button>
                      <Button
                        variant="outline"
                        disabled={selected === latest}
                        onClick={() =>
                          choose(dates[dates.indexOf(selected) + 1])
                        }
                      >
                        다음 거래일 →
                      </Button>
                    </div>
                    <div
                      className="flex flex-wrap gap-2"
                      aria-label="자료 조회 기간"
                    >
                      {[1, 7, 30, 90].map((n) => (
                        <Button
                          key={n}
                          size="sm"
                          aria-pressed={!custom && days === n}
                          variant={
                            !custom && days === n ? 'default' : 'outline'
                          }
                          onClick={() => update('days', String(n))}
                        >
                          {n === 1 ? '당일' : `이전 ${n}일`}
                        </Button>
                      ))}
                    </div>
                    <div className="flex flex-wrap items-end gap-3">
                      <label className="text-caption">
                        자료 시작일
                        <Input
                          type="date"
                          aria-label="자료 시작일"
                          className="mt-1 w-auto"
                          value={start}
                          max={selected}
                          onChange={(e) => {
                            const v = e.target.value
                            if (validDay(v) && v <= selected) update('from', v)
                            else
                              setNotice(
                                '시작일은 선택 거래일 이전이어야 합니다.',
                              )
                          }}
                        />
                      </label>
                      <label className="text-caption">
                        공개 기준
                        <select
                          className={`ml-2 ${fieldClass}`}
                          value={cutoff}
                          onChange={(e) => update('cutoff', e.target.value)}
                        >
                          <option value="end">선택일 종료</option>
                          <option value="close">정규장 마감</option>
                        </select>
                      </label>
                    </div>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={after}
                        onChange={(e) =>
                          update('after', e.target.checked ? '1' : '0')
                        }
                      />
                      이후 7일 해설도 보기
                    </label>
                    <p className="text-caption text-muted-foreground">
                      선택일 포함 달력일 기준 ·{' '}
                      {market === 'kr'
                        ? '한국 시간, 정규장 15:30'
                        : '뉴욕 시간, 정규장 16:00 (조기 폐장일은 별도 확인)'}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
          {selected && (
            <div
              className="company-research-evidence"
              tabIndex={0}
              aria-label="선택 구간 자료 목록"
            >
              <CompanyEvidence
                key={`${company}:research`}
                company={company}
                market={market}
                range={{ start, end: selected, cutoff, after }}
              />
            </div>
          )}
        </div>
      </div>}
      {!original && !selected && overview}
    </>
  )
}
