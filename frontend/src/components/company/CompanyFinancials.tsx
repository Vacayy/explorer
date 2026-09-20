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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PageContainer } from '@/components/shared/PageContainer'
import FinancialsPage from '@/components/financials/FinancialsPage'
import { formatKrw } from '@/utils/format'
import { quarterRows } from '@/utils/companyResearch'
import { companyResearchSearch } from '@/components/layout/navConfig'

export function FinancialPreview({ stockCode }: { stockCode: string }) {
  const [params] = useSearchParams()
  const query = useFinancials(stockCode, 'IS', 'quarterly', 3, 'CFS', {
    storedOnly: true,
  })
  const rows = quarterRows(query.data),
    latest = rows.at(-1)
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>최근 분기 실적</CardTitle>
        <Link
          className="text-sm text-primary hover:underline"
          to={`/analyze/${stockCode}/financials${companyResearchSearch(params.toString())}`}
        >
          실적·사업 보기 →
        </Link>
      </CardHeader>
      <CardContent>
        {query.isPending ? (
          <p className="text-sm text-muted-foreground">
            실적을 불러오는 중입니다.
          </p>
        ) : query.isError ? (
          <Button variant="outline" onClick={() => void query.refetch()}>
            실적 다시 불러오기
          </Button>
        ) : latest ? (
          <>
            <p className="mb-3 text-caption text-muted-foreground">
              {latest.period} · {query.data?.fs_div === 'CFS' ? '연결' : '별도'}{' '}
              · 단일 분기 · DART 최신 확보본
            </p>
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[
                [
                  '매출액',
                  latest.revenue == null ? '미확보' : formatKrw(latest.revenue),
                ],
                [
                  '영업이익',
                  latest.profit == null ? '미확보' : formatKrw(latest.profit),
                ],
                [
                  '영업이익률',
                  latest.margin == null
                    ? '산출 불가'
                    : latest.margin.toFixed(1) + '%',
                ],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-caption text-muted-foreground">
                    {label}
                  </dt>
                  <dd className="mt-1 text-lg font-semibold tabular-nums">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            확보된 분기 실적이 없습니다.
          </p>
        )}
      </CardContent>
    </Card>
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
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>사업부별 매출 구성</CardTitle>
        {years.length > 0 && (
          <label className="text-caption">
            연간 기준{' '}
            <select
              className="rounded-md border bg-background p-2"
              value={year}
              onChange={(e) => setChosen(e.target.value)}
            >
              {years.map((y) => (
                <option key={y}>{y}</option>
              ))}
            </select>
          </label>
        )}
      </CardHeader>
      <CardContent>
        {isPending ? (
          <p>사업부 자료를 불러오는 중입니다.</p>
        ) : isError ? (
          <Button onClick={() => void refetch()}>다시 불러오기</Button>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            사업부별 매출 자료를 아직 확보하지 못했습니다. 임의의 구성비를
            표시하지 않습니다.
          </p>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
              {valid && (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={rows}
                      dataKey="ratio"
                      nameKey="segment_name"
                      innerRadius={55}
                      outerRadius={85}
                    >
                      {rows.map((r, i) => (
                        <Cell key={r.id} fill={`var(--chart-${(i % 5) + 1})`} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v) => `${Number(v).toFixed(1)}%`} />
                  </PieChart>
                </ResponsiveContainer>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className="p-2 text-left">사업부</th>
                      <th className="p-2 text-right">매출액</th>
                      <th className="p-2 text-right">공개 비중</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="border-t">
                        <td className="p-2">{r.segment_name}</td>
                        <td className="p-2 text-right">
                          {r.revenue == null ? '미확보' : formatKrw(r.revenue)}
                        </td>
                        <td className="p-2 text-right">
                          {r.ratio == null ? '미확보' : `${r.ratio}%`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <p className="mt-3 text-caption text-muted-foreground">
              저장된 연간 사업부 데이터 · 연결조정·원문 출처는 별도 확인이
              필요합니다.
              {!valid &&
                ' 전체 비중을 확인할 수 없어 도넛 차트를 표시하지 않습니다.'}
            </p>
          </>
        )}
        <Link
          className="mt-4 inline-block text-caption text-primary hover:underline"
          to={`/analyze/${stockCode}/business${companyResearchSearch(params.toString())}`}
        >
          사업부 데이터 관리 →
        </Link>
      </CardContent>
    </Card>
  )
}
export default function CompanyFinancials({
  stockCode,
  corpCode,
}: {
  stockCode: string
  corpCode: string
}) {
  const [sp, setSp] = useSearchParams(),
    [count, setCount] = useState(8),
    [selected, setSelected] = useState('')
  const table = sp.get('view') === 'statements'
  const query = useFinancials(stockCode, 'IS', 'quarterly', 4, 'CFS', {
    enabled: !table,
    storedOnly: true,
  })
  const rows = quarterRows(query.data),
    shown = rows.slice(-count)
  const current = shown.find((r) => r.period === selected) || shown.at(-1)
  const previous = current
    ? rows.find(
        (r) =>
          r.period ===
          `${String(Number(current.period.slice(0, 2)) - 1).padStart(2, '0')}${current.period.slice(2)}`,
      )
    : null
  const growth =
    current?.revenue != null &&
    previous?.revenue != null &&
    previous.revenue > 0
      ? ((current.revenue - previous.revenue) / previous.revenue) * 100
      : null
  return (
    <PageContainer>
      <div className="flex flex-wrap gap-2">
        <Button
          variant={!table ? 'default' : 'outline'}
          onClick={() => setSp(previous => { const next = new URLSearchParams(previous); next.delete('view'); return next })}
        >
          실적·사업
        </Button>
        <Button
          variant={table ? 'default' : 'outline'}
          onClick={() => setSp(previous => { const next = new URLSearchParams(previous); next.set('view', 'statements'); return next })}
        >
          재무제표 상세
        </Button>
        <Link
          className="self-center px-2 text-sm text-primary"
          to={`/analyze/${stockCode}/valuation${companyResearchSearch(sp.toString())}`}
        >
          밸류에이션 →
        </Link>
      </div>
      {table ? (
        <FinancialsPage stockCode={stockCode} corpCode={corpCode} />
      ) : (
        <>
          <Card>
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle>분기 실적 추이</CardTitle>
                <p className="mt-2 text-caption text-muted-foreground">
                  {query.data?.fs_div === 'OFS' ? '별도' : '연결'} · 단일 분기 ·
                  억원 / % · DART 최신 확보본
                </p>
              </div>
              <label className="text-caption">
                표시 구간{' '}
                <select
                  className="rounded-md border bg-background p-2"
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                >
                  {[4, 8, 12].map((n) => (
                    <option key={n} value={n}>
                      최근 {n}개 분기
                    </option>
                  ))}
                </select>
              </label>
            </CardHeader>
            <CardContent className="space-y-6">
              {query.isPending ? (
                <p>분기 실적을 불러오는 중입니다.</p>
              ) : query.isError ? (
                <Button onClick={() => void query.refetch()}>
                  실적 다시 불러오기
                </Button>
              ) : shown.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  확보된 분기 손익계산서가 없습니다.
                </p>
              ) : (
                <>
                  {(['revenue', 'profit', 'margin'] as const).map((key, i) => (
                    <section key={key}>
                      <h3 className="mb-2 text-sm font-semibold">
                        {
                          [
                            '매출액 · 억원',
                            '영업이익 · 억원',
                            '영업이익률 · %',
                          ][i]
                        }
                      </h3>
                      <ResponsiveContainer width="100%" height={190}>
                        {key === 'margin' ? (
                          <LineChart data={shown}>
                            <CartesianGrid
                              vertical={false}
                              stroke="var(--border)"
                            />
                            <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                            <YAxis tick={{ fontSize: 12 }} width={65} />
                            <Tooltip
                              formatter={(v) => `${Number(v).toFixed(1)}%`}
                            />
                            <ReferenceLine
                              y={0}
                              stroke="var(--muted-foreground)"
                            />
                            <Line
                              dataKey="margin"
                              name="영업이익률"
                              stroke="var(--chart-3)"
                              strokeWidth={2}
                              connectNulls={false}
                              isAnimationActive={false}
                            />
                          </LineChart>
                        ) : (
                          <BarChart
                            data={shown.map((r) => ({
                              ...r,
                              [key]: r[key] == null ? null : r[key]! / 1e8,
                            }))}
                          >
                            <CartesianGrid
                              vertical={false}
                              stroke="var(--border)"
                            />
                            <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                            <YAxis tick={{ fontSize: 12 }} width={65} />
                            <Tooltip
                              formatter={(v) =>
                                `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })}억원`
                              }
                            />
                            <ReferenceLine
                              y={0}
                              stroke="var(--muted-foreground)"
                            />
                            <Bar
                              dataKey={key}
                              name={key === 'revenue' ? '매출액' : '영업이익'}
                              fill={`var(--chart-${i + 1})`}
                              isAnimationActive={false}
                            />
                          </BarChart>
                        )}
                      </ResponsiveContainer>
                    </section>
                  ))}
                  <section className="space-y-3 border-t pt-4">
                    <label className="text-sm font-medium">
                      실적 확인{' '}
                      <select
                        className="ml-2 rounded-md border bg-background p-2"
                        value={current?.period || ''}
                        onChange={(e) => setSelected(e.target.value)}
                      >
                        {shown.map((r) => (
                          <option key={r.period}>{r.period}</option>
                        ))}
                      </select>
                    </label>
                    <p className="text-sm leading-relaxed">
                      {current?.period} 매출액{' '}
                      {current?.revenue == null
                        ? '미확보'
                        : formatKrw(current.revenue)}
                      , 영업이익{' '}
                      {current?.profit == null
                        ? '미확보'
                        : formatKrw(current.profit)}
                      , 영업이익률{' '}
                      {current?.margin == null
                        ? '산출 불가'
                        : `${current.margin.toFixed(1)}%`}
                      .
                      {growth != null &&
                        ` 매출은 전년 동기 대비 ${Math.abs(growth).toFixed(1)}% ${growth >= 0 ? '증가' : '감소'}했습니다.`}
                    </p>
                    <p className="text-caption text-muted-foreground">
                      수치로 확인한 변화입니다. 회사 설명과 외부 해석은 원문에서
                      확인하세요. 회계분기와 자료 공개일은 다릅니다.
                    </p>
                    <Link
                      className="text-sm text-primary hover:underline"
                      to={`/analyze/${stockCode}/mentions?${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(companyResearchSearch(sp.toString()))), source: 'disclosure' })}`}
                    >
                      공시 근거 확인 →
                    </Link>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <caption className="py-2 text-left text-caption text-muted-foreground">
                          차트 수치 · 결측은 미확보로 표시
                        </caption>
                        <thead>
                          <tr>
                            <th className="p-2 text-left">분기</th>
                            <th>매출액</th>
                            <th>영업이익</th>
                            <th>영업이익률</th>
                          </tr>
                        </thead>
                        <tbody>
                          {shown.map((r) => (
                            <tr key={r.period} className="border-t">
                              <td className="p-2">{r.period}</td>
                              <td className="text-center">
                                {r.revenue == null
                                  ? '미확보'
                                  : formatKrw(r.revenue)}
                              </td>
                              <td className="text-center">
                                {r.profit == null
                                  ? '미확보'
                                  : formatKrw(r.profit)}
                              </td>
                              <td className="text-center">
                                {r.margin == null
                                  ? '산출 불가'
                                  : `${r.margin.toFixed(1)}%`}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                </>
              )}
            </CardContent>
          </Card>
          <Segments stockCode={stockCode} />
        </>
      )}
    </PageContainer>
  )
}
