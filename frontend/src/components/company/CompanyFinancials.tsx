import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  Line,
  LineChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Pie,
  PieChart,
  Cell,
} from 'recharts'
import { useFinancials } from '@/hooks/useFinancials'
import { useBusinessSegments } from '@/hooks/useBusiness'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { InfoTip } from '@/components/shared/InfoTip'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { quarterCount } from '@/lib/dossier'
import { PageContainer } from '@/components/shared/PageContainer'
import FinancialsPage from '@/components/financials/FinancialsPage'
import { formatKrw, formatPercent, formatRatio } from '@/utils/format'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { quarterRows } from '@/utils/companyResearch'
import { companyResearchSearch } from '@/components/layout/navConfig'

/** 국내 개요 '최근 분기 실적' — 최근 분기 매출·영업이익과 4분기 표(모바일은 값 두 개만) */
export function FinancialPreview({ stockCode }: { stockCode: string }) {
  const [params] = useSearchParams()
  const query = useFinancials(stockCode, 'IS', 'quarterly', 3, 'CFS', {
    storedOnly: true,
  })
  // 아직 공시되지 않은 분기(값 전부 빈칸)는 건너뛰고, 직전 4분기 대비 매출 YoY를 붙인다
  const all = quarterRows(query.data)
  const rows = all
    .map((r, i) => {
      const prev = all[i - 4]?.revenue
      return { ...r, yoy: r.revenue != null && prev != null && prev > 0 ? ((r.revenue - prev) / prev) * 100 : null }
    })
    .filter((r) => r.revenue != null || r.profit != null)
  const bars = rows.slice(-8)
  const recent = rows.slice(-4)
  const latest = rows.at(-1)
  return (
    <Card className="min-w-0 gap-0 py-0" aria-label="최근 분기 실적">
      <header className="flex flex-wrap items-center gap-x-2 border-b px-4 py-3">
        <h2 className="text-section font-semibold">최근 분기 실적</h2>
        {latest && <span className="text-caption text-muted-foreground">{query.data?.fs_div === 'OFS' ? '별도' : '연결'} · {latest.period}</span>}
        <span className="ml-auto" />
        <Link className="text-xs text-muted-foreground hover:text-foreground" to={`/analyze/${stockCode}/financials${companyResearchSearch(params.toString())}`}>실적·사업 보기 ›</Link>
      </header>
      <div className="space-y-3 p-4">
        {query.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : query.isError ? (
          <ErrorState message="실적을 불러오지 못했습니다." onRetry={() => void query.refetch()} />
        ) : latest ? (
          <>
            {/* 시안: 매출·영업이익 단일 분기 미니 막대(회색, 최근 분기 글자색 + 값) */}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(240px,100%),1fr))] gap-4">
              <MiniQuarterBars label="매출액 · 단일 분기" points={bars.map((r) => ({ period: r.period, value: r.revenue }))} />
              <MiniQuarterBars label="영업이익 · 단일 분기" points={bars.map((r) => ({ period: r.period, value: r.profit }))} />
            </div>
            <Table className="max-sm:hidden">
              <TableHeader>
                <TableRow>
                  <TableHead>분기</TableHead>
                  <TableHead className="text-right">매출액</TableHead>
                  <TableHead className="text-right">영업이익</TableHead>
                  <TableHead className="text-right">영업이익률</TableHead>
                  <TableHead className="text-right">매출 YoY</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...recent].reverse().map((r) => (
                  <TableRow key={r.period}>
                    <TableCell className="font-mono tabular-nums">{r.period}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{formatKrw(r.revenue)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{formatKrw(r.profit)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{formatRatio(r.margin)}</TableCell>
                    <TableCell className={`text-right font-mono tabular-nums ${r.yoy == null ? '' : r.yoy > 0 ? 'text-up-ink' : r.yoy < 0 ? 'text-down-ink' : ''}`}>{formatPercent(r.yoy)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">확보된 분기 실적이 없습니다.</p>
        )}
      </div>
    </Card>
  )
}
/** 분기 미니 막대 — 0 아래(적자)·빈 분기는 바닥선만. 금액 라벨은 최근 분기 하나 */
function MiniQuarterBars({ label, points }: { label: string; points: { period: string; value: number | null }[] }) {
  const n = points.length
  if (!n) return null
  const max = Math.max(1, ...points.map((p) => p.value ?? 0))
  const slot = 504 / n
  const w = Math.min(40, slot * 0.64)
  return (
    <div className="min-w-0">
      <span className="text-caption text-muted-foreground">{label}</span>
      <svg viewBox="0 0 520 150" role="img" aria-label={`${label} ${n}분기`} className="block h-auto w-full">
        {points.map((p, i) => {
          const x = 8 + i * slot + (slot - w) / 2
          const h = p.value != null && p.value > 0 ? Math.max(2, (p.value / max) * 110) : 1
          const last = i === n - 1
          return (
            <g key={p.period}>
              <rect x={x} y={128 - h} width={w} height={h} rx={2} fill={last ? 'var(--ink)' : 'var(--series)'}>
                <title>{`${p.period} ${formatKrw(p.value)}`}</title>
              </rect>
              <text x={x + w / 2} y={144} textAnchor="middle" fontSize={10} fill="var(--ink-3)" fontFamily="var(--font-mono)">{p.period}</text>
              {last && <text x={x + w / 2} y={Math.max(11, 128 - h - 5)} textAnchor="middle" fontSize={10.5} fontWeight={600} fill="var(--ink)" fontFamily="var(--font-mono)">{formatKrw(p.value)}</text>}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function Segments({ stockCode }: { stockCode: string }) {
  const [params] = useSearchParams()
  const { data, isPending, isError, refetch } = useBusinessSegments(stockCode)
  const [chosen, setChosen] = useState('')
  const years = [...new Set(data?.items.map((i) => i.bsns_year) || [])].sort(
    (a, b) => b - a,
  )
  const year = years.includes(Number(chosen)) ? Number(chosen) : years[0]
  const rows = data?.items.filter((i) => i.bsns_year === year) || []
  const sum = rows.reduce((a, b) => a + (b.ratio ?? 0), 0)
  const valid =
    rows.length > 0 &&
    rows.every((r) => r.ratio != null && r.ratio >= 0) &&
    Math.abs(sum - 100) < 0.1
  return (
    <Card className="min-w-0 gap-0 py-0" aria-label="사업부별 매출 구성">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-3">
        <h2 className="text-section font-semibold">사업부별 매출 구성</h2>
        <InfoTip label="사업부 구성 설명">저장된 연간 사업부 데이터입니다. 공시가 없으면 임의 비중을 표시하지 않습니다. 연결조정·원문 출처는 따로 확인이 필요합니다.</InfoTip>
        <span className="ml-auto" />
        {years.length > 1 && <SegmentTabs tabs={years.map((y) => ({ value: String(y), label: String(y) }))} value={String(year)} onChange={setChosen} />}
        <Link className="text-xs text-muted-foreground hover:text-foreground" to={`/analyze/${stockCode}/summary${companyResearchSearch(params.toString())}`}>기업 개요 ›</Link>
      </header>
      <div className="p-4">
        {isPending ? (
          <Skeleton className="h-28 w-full" />
        ) : isError ? (
          <ErrorState message="사업부 자료를 불러오지 못했습니다." onRetry={() => void refetch()} />
        ) : rows.length === 0 ? (
          <p className="bg-muted/60 p-3 text-sm text-muted-foreground">사업부별 매출 자료가 아직 없습니다</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-[200px_1fr]">
            {valid && (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={rows} dataKey="ratio" nameKey="segment_name" innerRadius={50} outerRadius={80}>
                    {rows.map((r, i) => (
                      <Cell key={r.id} fill={`var(--chart-${(i % 5) + 1})`} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => formatRatio(Number(v))} />
                </PieChart>
              </ResponsiveContainer>
            )}
            <Table className={valid ? '' : 'sm:col-span-2'}>
              <TableHeader>
                <TableRow>
                  <TableHead>사업부</TableHead>
                  <TableHead className="text-right">매출액</TableHead>
                  <TableHead className="text-right">공개 비중</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>{r.segment_name}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{r.revenue == null ? '-' : formatKrw(r.revenue)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{r.ratio == null ? '-' : formatRatio(r.ratio)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <Link
          className="mt-3 inline-block text-caption text-muted-foreground hover:text-foreground"
          to={`/analyze/${stockCode}/business${companyResearchSearch(params.toString())}`}
        >
          사업부 데이터 관리 ›
        </Link>
      </div>
    </Card>
  )
}

const QUARTER_TABS = [4, 8, 12].map((n) => ({ value: String(n), label: `최근 ${n}개 분기` }))

/** 막대 하나(최근 분기만 진하게) — 매출·영업이익 */
function QuarterBars({ title, data, k }: { title: string; data: ReturnType<typeof quarterRows>; k: 'revenue' | 'profit' }) {
  const last = data.length - 1
  return (
    <figure className="min-w-0" aria-label={title}>
      <figcaption className="mb-1 text-caption text-muted-foreground">{title}</figcaption>
      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={data.map((r) => ({ period: r.period, v: r[k] == null ? null : r[k]! / 1e8 }))} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <XAxis dataKey="period" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis hide />
          <Tooltip formatter={(v) => formatKrw(Number(v) * 1e8)} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" />
          <Bar dataKey="v" name={title} isAnimationActive={false}>
            {data.map((r, i) => <Cell key={r.period} fill={i === last ? 'var(--foreground)' : 'var(--color-chart-gray)'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}

/**
 * 국내 도시에 '실적·사업' 탭 (ia-redesign §4.13 · 시안 Dossier-KR-Financials) — 분기 매출·영업이익 막대 + 영업이익률 선(?n=4|8|12),
 * 분기 고르면 한 문장 확인(?period=), 분기 실적 표 | 사업부 구성. '재무제표 상세'는 ?view=statements.
 */
export default function CompanyFinancials({
  stockCode,
  corpCode,
}: {
  stockCode: string
  corpCode: string
}) {
  const [sp, setSp] = useSearchParams()
  const table = sp.get('view') === 'statements'
  const count = quarterCount(sp.get('n'))
  const query = useFinancials(stockCode, 'IS', 'quarterly', 4, 'CFS', {
    enabled: !table,
    storedOnly: true,
  })
  const setParam = (k: string, v: string | null) => setSp((previous) => {
    const next = new URLSearchParams(previous)
    if (v) next.set(k, v); else next.delete(k)
    return next
  }, { replace: true, preventScrollReset: true })
  const all = quarterRows(query.data)
  const rows = all.map((r) => {
    const prev = all.find((p) => p.period === `${String(Number(r.period.slice(0, 2)) - 1).padStart(2, '0')}${r.period.slice(2)}`)?.revenue
    return { ...r, yoy: r.revenue != null && prev != null && prev > 0 ? ((r.revenue - prev) / prev) * 100 : null }
  })
  const shown = rows.slice(-count)
  const current = shown.find((r) => r.period === sp.get('period')) || shown.at(-1)
  const growth = current?.yoy ?? null
  const fs = query.data?.fs_div === 'OFS' ? '별도' : '연결'
  return (
    <PageContainer>
      <div className="flex flex-wrap items-center gap-2">
        <SegmentTabs
          tabs={[{ value: 'summary', label: '실적·사업' }, { value: 'statements', label: '재무제표 상세' }]}
          value={table ? 'statements' : 'summary'}
          onChange={(v) => setParam('view', v === 'statements' ? 'statements' : null)}
        />
        <Link className="px-2 text-sm font-medium hover:underline" to={`/analyze/${stockCode}/valuation${companyResearchSearch(sp.toString())}`}>밸류에이션 ›</Link>
      </div>
      {table ? (
        <FinancialsPage stockCode={stockCode} corpCode={corpCode} />
      ) : (
        <>
          <Card className="gap-0 py-0" aria-label="분기 실적 추이">
            <header className="flex flex-wrap items-center gap-x-2 gap-y-2 border-b px-4 py-3">
              <h2 className="text-section font-semibold">분기 실적 추이</h2>
              <span className="text-caption text-muted-foreground">{fs} · 단일 분기</span>
              <span className="ml-auto" />
              <SegmentTabs tabs={QUARTER_TABS} value={String(count)} onChange={(v) => setParam('n', v === '8' ? null : v)} />
            </header>
            <div className="space-y-4 p-4">
              {query.isPending ? (
                <div role="status" aria-label="분기 실적 불러오는 중" className="grid gap-4 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 w-full" />)}</div>
              ) : query.isError ? (
                <ErrorState message="분기 실적을 불러오지 못했습니다." onRetry={() => void query.refetch()} />
              ) : shown.length === 0 ? (
                <p className="text-sm text-muted-foreground">확보된 분기 손익계산서가 없습니다.</p>
              ) : (
                <>
                  <div className="grid gap-4 lg:grid-cols-3">
                    <QuarterBars title="매출액" data={shown} k="revenue" />
                    <QuarterBars title="영업이익" data={shown} k="profit" />
                    <figure className="min-w-0" aria-label="영업이익률">
                      <figcaption className="mb-1 text-caption text-muted-foreground">영업이익률 · %</figcaption>
                      <ResponsiveContainer width="100%" height={150}>
                        <LineChart data={shown} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                          <CartesianGrid vertical={false} stroke="var(--border)" />
                          <XAxis dataKey="period" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                          <YAxis tick={{ fontSize: 10 }} width={36} />
                          <Tooltip formatter={(v) => formatRatio(Number(v))} />
                          <ReferenceLine y={0} stroke="var(--muted-foreground)" />
                          <Line dataKey="margin" name="영업이익률" stroke="var(--foreground)" strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </figure>
                  </div>
                  <section aria-label="실적 확인" className="space-y-2 border-t pt-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="flex items-center gap-1 text-sm font-semibold">실적 확인
                        <InfoTip label="실적 확인 설명">수치로 확인한 변화입니다. 회사 설명과 외부 해석은 원문에서 확인하세요. 회계분기와 자료 공개일은 다릅니다.</InfoTip>
                      </h3>
                      <SegmentTabs tabs={shown.slice(-4).map((r) => ({ value: r.period, label: r.period }))} value={current?.period ?? ''}
                        onChange={(v) => setParam('period', v === shown.at(-1)?.period ? null : v)} />
                    </div>
                    <p className="text-sm leading-relaxed">
                      {current?.period} 매출액 {formatKrw(current?.revenue)}, 영업이익 {formatKrw(current?.profit)}, 영업이익률 {formatRatio(current?.margin)}.
                      {growth != null && ` 매출은 전년 동기 대비 ${Math.abs(growth).toFixed(1)}% ${growth >= 0 ? '증가' : '감소'}했습니다.`}
                    </p>
                    <Link
                      className="inline-block text-sm font-medium hover:underline"
                      to={`/analyze/${stockCode}/mentions?${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(companyResearchSearch(sp.toString()))), source: 'disclosure' })}`}
                    >
                      공시 근거 확인 ›
                    </Link>
                  </section>
                </>
              )}
            </div>
          </Card>
          <div className="grid gap-3 lg:grid-cols-2">
            <Card className="min-w-0 gap-0 py-0" aria-label="분기 실적 표">
              <header className="flex flex-wrap items-center gap-x-2 border-b px-4 py-3">
                <h2 className="text-section font-semibold">분기 실적 표</h2>
                <span className="text-caption text-muted-foreground">최근 {shown.length}개 분기</span>
              </header>
              <div className="px-4 py-2">
                {query.isPending ? <Skeleton className="h-40 w-full" /> : shown.length === 0 ? <p className="py-4 text-sm text-muted-foreground">확보된 분기 실적이 없습니다.</p> : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>분기</TableHead>
                        <TableHead className="text-right">매출액</TableHead>
                        <TableHead className="text-right">영업이익</TableHead>
                        <TableHead className="text-right">영업이익률</TableHead>
                        <TableHead className="text-right">매출 전년 대비</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {[...shown].reverse().map((r) => (
                        <TableRow key={r.period}>
                          <TableCell className="font-mono tabular-nums">{r.period}</TableCell>
                          <TableCell className="text-right font-mono tabular-nums">{formatKrw(r.revenue)}</TableCell>
                          <TableCell className="text-right font-mono tabular-nums">{formatKrw(r.profit)}</TableCell>
                          <TableCell className="text-right font-mono tabular-nums">{formatRatio(r.margin)}</TableCell>
                          <TableCell className={`text-right font-mono tabular-nums ${r.yoy == null ? '' : r.yoy > 0 ? 'text-up-ink' : r.yoy < 0 ? 'text-down-ink' : ''}`}>{formatPercent(r.yoy)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>
            </Card>
            <Segments stockCode={stockCode} />
          </div>
        </>
      )}
    </PageContainer>
  )
}
