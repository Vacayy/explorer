import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { DetailLink } from '@/components/shared/DetailNavigation'
import { usePortfolioFlow } from '@/hooks/usePortfolio'

/** 자료 흐름 — 팔로우 자료에서 이 종목이 어떻게 이야기되나(portfolio-intelligence §3). */
export function FlowCard({ code }: { code: string }) {
  const flows = usePortfolioFlow()
  const f = flows.data?.find(x => x.code === code)
  const total = f?.series.reduce((a, d) => a + d.n, 0) ?? 0
  return <Card>
    <CardHeader className="flex-row items-center justify-between"><CardTitle>자료 흐름</CardTitle>
      <DetailLink to={`/analyze/${code}/mentions`} className="text-sm text-primary hover:underline">전체 →</DetailLink></CardHeader>
    <CardContent className="space-y-3">
      {flows.isPending ? <Skeleton className="h-32 w-full" />
        : flows.isError ? <Button variant="outline" size="sm" onClick={() => void flows.refetch()}>다시 불러오기</Button>
        : !f || !total ? <p className="text-sm text-muted-foreground">최근 14일 팔로우 자료에서 언급이 없습니다.</p>
        : <>
          <div className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
            <span>14일 {total}건 · 오늘 {f.today}건 · 7일 평균 {f.avg7}</span>
            {f.surge && <Badge variant="outline" className="text-caption text-hypothesis border-hypothesis/40">언급 급증</Badge>}
            {f.tone_shift && <Badge variant="outline" className="text-caption text-down border-down/40">부정 {f.neg_prev_pct}%→{f.neg_today_pct}%</Badge>}
          </div>
          <div className="h-20"><ResponsiveContainer><BarChart data={f.series} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" hide />
            <Tooltip cursor={{ fill: 'var(--muted)' }} formatter={(v, k) => [String(v), k === 'neg' ? '부정' : '언급']} labelFormatter={l => String(l).slice(5)} />
            <Bar dataKey="n" fill="var(--chart-1)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="neg" fill="var(--down)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart></ResponsiveContainer></div>
          {f.digest ? <div className="space-y-1 rounded-lg bg-muted/40 p-3 text-sm">
            <p className="text-caption text-muted-foreground">{f.digest.date} 1일 요약 · 자료 {f.digest.docs}건</p>
            {f.digest.insights && <p><span className="font-medium">새로운 점 </span>{f.digest.insights}</p>}
            {!f.digest.insights && f.digest.lead && <p className="line-clamp-3">{f.digest.lead}</p>}
          </div> : <p className="text-caption text-muted-foreground">아직 요약이 없습니다. 새 자료가 있는 날 16:50에 만듭니다.</p>}
        </>}
    </CardContent>
  </Card>
}
