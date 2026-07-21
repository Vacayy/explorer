import { useState } from "react"
import { Link } from "react-router-dom"
import { ChevronDown, FileText, Loader2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Markdown } from "@/components/shared/Markdown"
import { EmptyState } from "@/components/shared/ErrorState"
import { cn } from "@/lib/utils"

// 레이팅 색 — 한국 컨벤션(상승=빨강 up, 하락=파랑 down)
const RATING_CLS: Record<string, string> = {
  "Strong Buy": "text-up border-up/50 font-semibold",
  "Buy": "text-up border-up/40",
  "Hold": "text-muted-foreground",
  "Sell": "text-down border-down/50 font-semibold",
}

/**
 * 통합 리포트 뷰 (integrated-report, D-041) — 공유 인과 내러티브 취합 → 종목 재분석 → Top-down.
 * 내러티브 상세 인라인 + 리포트 탭 디테일 공용. 저장분 자동 표시 + '다시 생성'(refresh)만 재생성.
 * 최하단에 이 리포트를 구성한 내러티브 링크(어떤 인과 공유 내러티브로부터 나왔는지).
 */
export interface ReportResult {
  status: string
  title: string | null
  answer: string | null
  members: string[]
  stocks: { code: string; name: string; rating?: string; upside_pct?: number | null }[]
  debate?: {
    fundamental?: string; technical?: string; sentiment?: string
    bull?: string; bear?: string
  }
  cached?: boolean
  created_at?: string | null
}

export function ReportView({ topic }: { topic: string }) {
  const [nonce, setNonce] = useState(0)
  const [refresh, setRefresh] = useState(false)
  const cached = useQuery(
    apiQuery<ReportResult>({
      key: ["spine", "report", "cached", topic],
      url: `/api/spine/report?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short, enabled: !!topic,
    }),
  )
  const compute = useQuery(
    apiComputeQuery<ReportResult>({
      key: ["spine", "report", "compute", topic, nonce],
      url: `/api/spine/report/compute?topic=${encodeURIComponent(topic)}${refresh ? "&refresh=1" : ""}`,
      enabled: nonce > 0,
    }),
  )
  const display = compute.data?.status === "ok" ? compute.data
    : cached.data?.status === "ok" ? cached.data : null
  const loading = nonce > 0 && (compute.isFetching || !compute.data)
  const failed = nonce > 0 && compute.data && compute.data.status !== "ok" && !display
  const run = (isRefresh: boolean) => { setRefresh(isRefresh); setNonce((n) => n + 1) }

  return (
    <Card>
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">통합 리포트</span>
          <span className="text-[11px] text-muted-foreground">공유 인과로 엮인 내러티브 + 종목 분석 → Top-down</span>
          {!loading && (
            <Button size="sm" variant={display ? "outline" : "default"} className="ml-auto h-7"
              onClick={() => run(!!display)}>
              <FileText className="h-3.5 w-3.5" /> {display ? "다시 생성" : "리포트 생성"}
            </Button>
          )}
        </div>
        {loading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            내러티브 취합 → 종목 재분석 → 리포트 종합 중… (연쇄 LLM, 수 분)
          </div>
        )}
        {failed && <EmptyState message="리포트를 생성하지 못했습니다 — 잠시 후 다시 시도." />}
        {display?.answer && (
          <Card className="bg-[color-mix(in_srgb,var(--primary)_5%,var(--card))]">
            <CardContent className="py-4 space-y-3">
              {display.title && <h3 className="text-base font-bold">{display.title}</h3>}
              <Markdown>{display.answer}</Markdown>
              {display.stocks.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 border-t pt-2 text-[11px]">
                  <span className="text-muted-foreground">분석 종목</span>
                  {display.stocks.map((s) => (
                    <span key={s.code} className="inline-flex items-center gap-1">
                      <Link to={`/analyze/${s.code}/summary`} className="text-primary hover:underline">{s.name}</Link>
                      {s.rating && (
                        <Badge variant="outline" className={cn("text-[9px]", RATING_CLS[s.rating] ?? "")}>
                          {s.rating}{s.upside_pct != null ? ` ${Math.round(s.upside_pct)}%` : ""}
                        </Badge>
                      )}
                    </span>
                  ))}
                </div>
              )}
              {display.members.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 border-t pt-2 text-[11px]">
                  <span className="text-muted-foreground">구성 내러티브 (공유 인과)</span>
                  {display.members.map((m) => (
                    <Link key={m} to={`/narrative?topic=${encodeURIComponent(m)}`}>
                      <Badge variant="secondary" className="text-[10px] font-normal hover:bg-secondary/70">{m}</Badge>
                    </Link>
                  ))}
                </div>
              )}
              {display.debate && (display.debate.bull || display.debate.bear) && (
                <Collapsible className="border-t pt-2">
                  <CollapsibleTrigger className="group/dbt flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
                    <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/dbt:rotate-180" />
                    논쟁·분석 (이 리포트가 어떻게 벼려졌나)
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="space-y-2 pt-2 text-[11px] leading-snug">
                      {display.debate.bull && <div className="rounded-md border border-up/30 bg-up/5 px-2.5 py-1.5"><span className="font-semibold text-up">강세 (Bull)</span><div className="text-muted-foreground whitespace-pre-wrap mt-0.5">{display.debate.bull}</div></div>}
                      {display.debate.bear && <div className="rounded-md border border-down/30 bg-down/5 px-2.5 py-1.5"><span className="font-semibold text-down">약세 (Bear)</span><div className="text-muted-foreground whitespace-pre-wrap mt-0.5">{display.debate.bear}</div></div>}
                      {display.debate.fundamental && <p className="text-muted-foreground"><span className="font-medium text-foreground">펀더:</span> {display.debate.fundamental}</p>}
                      {display.debate.technical && <p className="text-muted-foreground"><span className="font-medium text-foreground">기술:</span> {display.debate.technical}</p>}
                      {display.debate.sentiment && <p className="text-muted-foreground"><span className="font-medium text-foreground">수급:</span> {display.debate.sentiment}</p>}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              )}
              <div className="text-[10px] text-muted-foreground/70 border-t pt-2">
                {display.cached && display.created_at ? `저장분 ${display.created_at.slice(0, 10)}` : "방금 생성"}
                {" · 애널리스트 팀·Bull/Bear 논쟁·리드 판정 · 범위+조건부 · 검증 필요"}
              </div>
            </CardContent>
          </Card>
        )}
      </CardContent>
    </Card>
  )
}
