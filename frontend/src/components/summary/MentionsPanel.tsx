import { Link } from "react-router-dom"
import { ChevronDown } from "lucide-react"
import { useSpineFeed } from "@/hooks/useSpineFeed"
import { useSpineSignals } from "@/hooks/useSpineSignals"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { SourceBadge } from "@/components/shared/SourceBadge"
import KeywordsSection, { useStockKeywords } from "@/components/analyze/KeywordsSection"
import { formatRelativeTime } from "@/utils/format"

/**
 * 언급 패널 — 구 '언급' 탭을 종목 홈 우측(AI/언급 축)으로 흡수 (P2 후속).
 * 신호 이력 · 언급 문서(최근, 전체는 피드 필터로) · 매칭 키워드(접힘).
 */
export default function MentionsPanel({ stockCode }: { stockCode: string }) {
  const feed = useSpineFeed({ stock: stockCode, page: 1, size: 5 })
  const signals = useSpineSignals(undefined, 90)
  const stockSignals = (signals.data?.items ?? []).filter((s) => s.stock_code === stockCode)

  return (
    <>
      {/* 신호 이력 — 컴팩트 행 (스캔 표면 원칙: 상세는 탐색 화면이 담당) */}
      {stockSignals.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">신호 이력 (90일)</CardTitle>
          </CardHeader>
          <CardContent className="divide-y">
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
      )}

      {/* 언급 문서 — 최근 8건, 전체는 피드 필터 */}
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

      {/* 매칭 키워드 — 관리성 기능이라 접힘, 승인 대기는 배지로 표면화 */}
      <MatchingCollapsed stockCode={stockCode} />
    </>
  )
}

function MatchingCollapsed({ stockCode }: { stockCode: string }) {
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
