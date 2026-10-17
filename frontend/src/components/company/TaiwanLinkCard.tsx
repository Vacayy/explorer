import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { SparkLine } from "@/components/shared/Spark"
import { KrConfirmStrip, TW_RELATION, TwStateBadge, twEvidenceText } from "@/components/shared/TwLinkSignal"
import { useKrConfirm, useTwLinks } from "@/hooks/useTwRevenue"
import { formatPercent } from "@/utils/format"

/**
 * 종목 상세 › 대만 연결 신호 (docs/specs/tw-revenue.md §6) — 연결된 대만 회사들의 월매출 3개월 YoY와 가속·둔화,
 * 사업 근거 확신도와 숫자 근거(분기 YoY 상관)를 같이 보인다. 연결이 없는 종목에서는 그리지 않는다.
 */
export function TaiwanLinkCard({ stockCode }: { stockCode: string }) {
  const q = useTwLinks(stockCode)
  const confirm = useKrConfirm(stockCode)
  if (q.isLoading) return <Skeleton className="h-28 w-full rounded-xl" />
  if (q.isError) return <ErrorState message="대만 연결 신호를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
  const items = q.data?.items ?? []
  if (!items.length) return null
  return <Card>
    <CardHeader className="pb-2">
      <CardTitle className="flex flex-wrap items-baseline gap-2 text-card-title">
        대만 연결 신호<span className="text-caption font-normal text-muted-foreground">대만 월매출 {q.data?.as_of} 공시 기준</span>
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-3">
      {/* 한국 쪽 교차 확인 — 대만 신호가 한국 수출·공시에서도 보이나 */}
      {confirm.data?.[0] && <div className="space-y-1.5 border-b pb-3">
        <p className="text-caption font-medium text-muted-foreground">한국 확인 신호</p>
        <KrConfirmStrip c={confirm.data[0]} />
      </div>}
      {items.map(l => (
        <div key={`${l.relation}-${l.tw.map(t => t.code).join("")}`} className="grid gap-x-4 gap-y-1 border-b pb-3 last:border-b-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_120px]">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5 text-sm">
              <Badge variant="secondary" className="text-[11px]">{TW_RELATION[l.relation]}</Badge>
              <span className="font-medium">{l.tw.map(t => t.name).join(" · ")}</span>
              <TwStateBadge link={l} />
              <span className="text-[11px] text-muted-foreground" title="제품·고객 구조로 본 연결의 확실성">사업 근거 {l.confidence}</span>
            </div>
            <p className="text-caption text-muted-foreground">{l.reason}</p>
            <p className="text-caption text-muted-foreground">
              3개월 YoY <span className="tabular-nums text-foreground">{formatPercent(l.yoy_3m)}</span>
              {l.yoy_3m_prev != null && <> (3개월 전 {formatPercent(l.yoy_3m_prev)})</>} · 숫자 근거: {twEvidenceText(l.evidence)}
            </p>
          </div>
          <div className="self-center" title="대만 연결 회사 합계의 월별 YoY(최근 24개월)">
            <SparkLine data={l.series.map(p => p.yoy)} height={36} />
          </div>
        </div>
      ))}
      <p className="text-caption text-muted-foreground">대만 월매출은 업황 방향 신호입니다. 한국 종목의 매출 전망이 아니며, 서버 ODM 매출에는 GPU 매입 원가가 섞여 있습니다.</p>
    </CardContent>
  </Card>
}
