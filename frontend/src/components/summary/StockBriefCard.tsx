import ReactMarkdown from "react-markdown"
import { Loader2, Scale } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { stockBriefQuery, stockBriefComputeQuery } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

/**
 * 종목 AI 브리프 — 도시에 첫 화면 (P2-1, product-v3.md §3).
 * "지금 이 종목에서 알아야 할 것": 다이제스트·신호·일정·내 논지를 종합.
 * 게으른 생성: 입력이 바뀐 경우에만 LLM (stale → compute 쿼리 자동 발화, 종목별 키잉).
 */
export default function StockBriefCard({ stockCode }: { stockCode: string }) {
  const { data } = useQuery(stockBriefQuery(stockCode))
  const compute = useQuery(stockBriefComputeQuery(stockCode, !!data?.stale))

  const b = compute.data ?? data
  // 재료 자체가 없으면(수집 언급·신호 0) 카드 생략 — 도시에를 비AI 데이터로만
  if (!b || (b.status === "empty" && !b.stale && !compute.isFetching)) return null

  return (
    <Card className="border-l-2 border-l-hypothesis">
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm">AI 브리프 — 지금 알아야 할 것</CardTitle>
        {b.created_at && (
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            {b.created_at.slice(0, 16).replace("T", " ")} 기준
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {compute.isFetching && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            새 재료를 반영해 브리프 생성 중… (수십 초 걸릴 수 있습니다)
          </div>
        )}
        {b.thesis_check && (
          <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
            <Scale className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
            <p className="text-xs">
              <span className="font-semibold text-hypothesis">내 논지 점검</span> {b.thesis_check}
            </p>
          </div>
        )}
        {b.brief && (
          <>
            <div className={`prose prose-sm dark:prose-invert max-w-none text-sm [&_h3]:text-[13px] [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:my-1.5 ${compute.isFetching ? "opacity-60" : ""}`}>
              <ReactMarkdown>{b.brief}</ReactMarkdown>
            </div>
            <div className="text-right">
              <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                AI 종합 · 열람 시점 갱신 — 검증 필요
              </Badge>
            </div>
          </>
        )}
        {!b.brief && !compute.isFetching && b.status === "unavailable" && (
          <p className="text-xs text-muted-foreground py-1">LLM 엔진이 연결되면 열람 시 자동 생성됩니다.</p>
        )}
        {!b.brief && !compute.isFetching && compute.isError && (
          <p className="text-xs text-muted-foreground py-1">브리프 생성에 실패했습니다. 다시 열람하면 재시도됩니다.</p>
        )}
      </CardContent>
    </Card>
  )
}
