import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown } from "lucide-react"
import api from "@/api/client"
import { useSpineFeed } from "@/hooks/useSpineFeed"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { Spark } from "@/components/shared/Spark"
import KeywordsSection, { useStockKeywords } from "@/components/analyze/KeywordsSection"
import { formatRelativeTime } from "@/utils/format"

/**
 * 종목 홈 우측 컬럼 조각들 — 구 '언급' 탭의 흡수 결과 (스캔 표면 원칙).
 * SignalHistoryCard / MentionDocsCard / MatchingCollapsed 를 개별 export.
 */

interface MomentumRow {
  stock_code: string | null
  daily?: number[]
}

/** 신호 이력 — 컴팩트 행 + 14일 언급 스파크라인 (탐색과 동일 문법) */
export function SignalHistoryCard({ stockCode }: { stockCode: string }) {
  const signals = useSpineSignals(undefined, 90)
  const stockSignals = (signals.data?.items ?? []).filter((s) => s.stock_code === stockCode)
  const { data: momentum } = useQuery({
    queryKey: ["spine", "momentum"],
    queryFn: async () => (await api.get("/api/spine/signals/momentum", { params: { limit: 30 } })).data as { items: MomentumRow[] },
    staleTime: 5 * 60_000,
  })
  const daily = momentum?.items.find((m) => m.stock_code === stockCode)?.daily

  if (stockSignals.length === 0 && !daily) return null

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <CardTitle className="text-sm">신호 이력 (90일)</CardTitle>
        {daily && <span className="ml-auto"><Spark data={daily} /></span>}
      </CardHeader>
      <CardContent className="divide-y">
        {stockSignals.length === 0 && (
          <p className="text-xs text-muted-foreground py-1">아직 신호가 없습니다.</p>
        )}
        {stockSignals.slice(0, 5).map((s) => (
          <div key={s.id} className="py-1.5 space-y-0.5">
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="secondary" className="text-[10px] shrink-0">
                {s.signal_type === "mention_surge" ? "언급 급증" : s.signal_type === "high_52w" ? "52주 신고가" : s.signal_type}
              </Badge>
              <span className="font-medium tabular-nums">
                {s.signal_type === "mention_surge"
                  ? `7일 ${s.payload.count_7d}회 (직전 ${s.payload.baseline_7d})`
                  : s.signal_type === "high_52w" ? `+${s.payload.breakout_pct}%` : ""}
              </span>
              <span className="ml-auto shrink-0 text-[10px] text-muted-foreground tabular-nums">{s.date}</span>
            </div>
            {s.interpretation && (
              <p className="text-[11px] text-muted-foreground line-clamp-2">{s.interpretation}</p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

/** 언급 문서 — 최근 5건, 전체는 피드 필터 */
export function MentionDocsCard({ stockCode }: { stockCode: string }) {
  const feed = useSpineFeed({ stock: stockCode, page: 1, size: 5 })
  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm">언급 문서</CardTitle>
        {(feed.data?.total ?? 0) > 0 && (
          <Link to={`/feed?stock=${stockCode}`}
            className="ml-auto text-[11px] text-muted-foreground hover:text-primary">
            전체 {feed.data!.total}건 →
          </Link>
        )}
      </CardHeader>
      <CardContent>
        {(feed.data?.items.length ?? 0) === 0 ? (
          <p className="text-xs text-muted-foreground py-1">아직 이 종목을 언급한 수집 문서가 없습니다.</p>
        ) : (
          <ul className="divide-y">
            {feed.data!.items.map((doc) => (
              <li key={doc.id} className="py-2 space-y-0.5">
                <div className="flex items-center gap-2">
                  <SourceBadge sourceType={doc.source_type} />
                  <Link to={`/doc/${doc.id}`} className="text-xs font-medium truncate hover:underline">
                    {doc.title || "(제목 없음)"}
                  </Link>
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground tabular-nums">
                    {formatRelativeTime(doc.published_at)}
                  </span>
                </div>
                {doc.summary && (
                  <p className="text-[11px] text-muted-foreground line-clamp-2">{doc.summary}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/** 매칭 키워드 — 관리성 기능이라 접힘, 승인 대기는 배지로 표면화 */
export function MatchingCollapsed({ stockCode }: { stockCode: string }) {
  const { data } = useStockKeywords(stockCode)
  const proposed = (data?.keywords ?? []).filter((k) => k.status === "proposed").length

  return (
    <Collapsible>
      <CollapsibleTrigger className="group/kw flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-data-[state=open]/kw:rotate-180" />
        매칭 키워드 관리
        {proposed > 0 && (
          <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">
            승인 대기 {proposed}
          </Badge>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 rounded-xl border px-4 py-3">
          <KeywordsSection stockCode={stockCode} plain />
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
