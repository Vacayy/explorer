import { useState } from "react"
import ReactMarkdown from "react-markdown"
import { ChevronDown, Loader2, Scale, TrendingDown, TrendingUp, Minus } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { stockBriefQuery, stockBriefComputeQuery, stockBriefHistoryQuery } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Expandable } from "@/components/shared/Expandable"

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
    <Card className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]">
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
        {b.revision_call && (
          <div className="flex gap-2 rounded-md bg-card/60 border px-3 py-2">
            {b.revision_call.direction === "up" ? <TrendingUp className="h-3.5 w-3.5 text-up shrink-0 mt-0.5" />
              : b.revision_call.direction === "down" ? <TrendingDown className="h-3.5 w-3.5 text-down shrink-0 mt-0.5" />
              : <Minus className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />}
            <p className="text-xs">
              <span className={`font-semibold ${b.revision_call.direction === "up" ? "text-up" : b.revision_call.direction === "down" ? "text-down" : "text-muted-foreground"}`}>
                추정치 방향 콜 — {b.revision_call.direction === "up" ? "상향 우세" : b.revision_call.direction === "down" ? "하향 우세" : "유지"}
              </span>{" "}
              {b.revision_call.rationale}
              <span className="block text-[10px] text-muted-foreground mt-0.5">
                AI 가설 — 기록되어 실제 컨센서스 변화와 대조됩니다
              </span>
            </p>
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
        {/* 근거 재료 — 이 브리프는 무엇을 보고 썼나 (언급 없이 공시만으로 쓰일 수도 있다) */}
        {(data?.evidence?.length ?? 0) > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] text-muted-foreground shrink-0">근거 재료</span>
            {data!.evidence!.map((e) => (
              <Badge key={e} variant="secondary" className="text-[10px] font-normal">{e}</Badge>
            ))}
          </div>
        )}
        {b.brief && (
          <>
            <Expandable collapsedHeight={300}>
              <div className={`prose prose-sm dark:prose-invert max-w-none text-sm [&_h3]:text-[13px] [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:my-1.5 ${compute.isFetching ? "opacity-60" : ""}`}>
                <ReactMarkdown>{b.brief}</ReactMarkdown>
              </div>
            </Expandable>
            <div className="text-right">
              <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                AI 종합 · 열람 시점 갱신 — 검증 필요
              </Badge>
            </div>
            <BriefHistory stockCode={stockCode} />
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

/** 지난 브리프 아카이브 — 펼칠 때만 조회 (append-only stock_briefs) */
function BriefHistory({ stockCode }: { stockCode: string }) {
  const [open, setOpen] = useState(false)
  const history = useQuery(stockBriefHistoryQuery(stockCode, open))
  return (
    <Collapsible className="border-t pt-2" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="group/bh flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
        <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/bh:rotate-180" />
        지난 브리프
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-3 pt-2">
          {history.isLoading && <p className="text-[11px] text-muted-foreground">불러오는 중…</p>}
          {history.data?.length === 0 && (
            <p className="text-[11px] text-muted-foreground">이전 브리프가 없습니다 — 재료가 바뀔 때마다 새 판이 쌓입니다.</p>
          )}
          {history.data?.map((h) => (
            <div key={h.created_at} className="rounded-md border px-3 py-2">
              <div className="text-[11px] text-muted-foreground tabular-nums mb-1">
                {h.created_at.slice(0, 16).replace("T", " ")}
              </div>
              {h.thesis_check && <p className="text-[11px] text-hypothesis mb-1">⚖ {h.thesis_check}</p>}
              <div className="prose prose-sm dark:prose-invert max-w-none text-xs [&_p]:my-1">
                <ReactMarkdown>{h.brief ?? ""}</ReactMarkdown>
              </div>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
