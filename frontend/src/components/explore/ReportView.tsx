import { useState } from "react"
import { Link } from "react-router-dom"
import { ChevronDown, FileText, History, Loader2 } from "lucide-react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Markdown } from "@/components/shared/Markdown"
import { EmptyState } from "@/components/shared/ErrorState"
import SaveButton from "@/components/shared/SaveButton"
import { ReportCharts, useReportFwdPer, useReportPrices } from "@/components/explore/report/ReportCharts"
import { ratingLabel, ratingTone, relabelRatings, reportSectionNames, sinceChange, splitReportBody } from "@/lib/judgment"
import { cn } from "@/lib/utils"
import { formatPer, formatPercent, formatStockPrice } from "@/utils/format"

// 레이팅 색 — 한국 컨벤션(상승=빨강 up, 하락=파랑 down). 말은 '상방 우위(비대칭 큼)·상방 우위·Hold·하방 우위'(ia-redesign §4.27, 11-04)
const RATING_CLS: Record<ReturnType<typeof ratingTone>, string> = {
  "up-strong": "text-up border-up/50 font-semibold",
  up: "text-up border-up/40",
  neutral: "text-muted-foreground",
  down: "text-down border-down/50 font-semibold",
}

const md = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`

/**
 * 통합 리포트 뷰 (integrated-report, D-041) — 공유 인과 내러티브 취합 → 종목 재분석 → Top-down.
 * 내러티브 상세 인라인 + Thesis › 내 판단 › 리포트 상세 공용. 저장분 자동 표시 + '다시 생성'(refresh)만 재생성(낡아도 자동 갱신 없음, 11-04 ②).
 * 맨 위 '작성 이후' 한 줄(Top-pick 주가·선행 PER — 관측이지 판정 아님), 산업 분석 이하 긴 본문은 접는다(§4.27 C).
 * 옛 리포트의 영문 레이팅(Strong Buy·Buy·Sell)은 보일 때 새 말로 바꾼다(저장 원문 그대로).
 * 최하단에 이 리포트를 구성한 내러티브 링크(어떤 인과 공유 내러티브로부터 나왔는지).
 */
export interface ReportResult {
  status: string
  id?: number | null
  title: string | null
  answer: string | null
  members: string[]
  stocks: { code: string; name: string; rating?: string; upside_pct?: number | null; downside_pct?: number | null }[]
  top_pick?: string | null
  debate?: {
    fundamental?: string; technical?: string; sentiment?: string
    bull?: string; bear?: string
  }
  cached?: boolean
  created_at?: string | null
}
interface ReportVersion { id: number; title: string | null; top_pick: string | null; created_at: string }

export function ReportView({ topic, initialVersionId = null }: { topic: string; initialVersionId?: number | null }) {
  const qc = useQueryClient()
  const [nonce, setNonce] = useState(0)
  const [refresh, setRefresh] = useState(false)
  const [versionId, setVersionId] = useState<number | null>(initialVersionId)   // 과거 버전 열람 (null=최신, D-047)
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
  const history = useQuery(
    apiQuery<ReportVersion[]>({
      key: ["spine", "report", "history", topic],
      url: `/api/spine/report/history?topic=${encodeURIComponent(topic)}`,
      staleTime: STALE.short, enabled: !!topic,
    }),
  )
  const version = useQuery(
    apiQuery<ReportResult>({
      key: ["spine", "report", "version", versionId],
      url: `/api/spine/report/version?id=${versionId}`,
      staleTime: STALE.short, enabled: versionId != null,
    }),
  )
  const display = versionId != null
    ? (version.data?.status === "ok" ? version.data : null)
    : compute.data?.status === "ok" ? compute.data
    : cached.data?.status === "ok" ? cached.data : null
  const loading = (nonce > 0 && (compute.isFetching || !compute.data)) || (versionId != null && version.isFetching && !version.data)
  const failed = nonce > 0 && compute.data && compute.data.status !== "ok" && !display
  const versions = history.data ?? []
  const viewingOld = versionId != null && versions.length > 0 && versions[0].id !== versionId
  const versionNo = display?.id != null ? versions.length - versions.findIndex((x) => x.id === display.id) : null
  const body = display?.answer ? splitReportBody(relabelRatings(display.answer)) : null
  const run = (isRefresh: boolean) => {
    setVersionId(null); setRefresh(isRefresh); setNonce((n) => n + 1)
    qc.invalidateQueries({ queryKey: ["spine", "report", "history", topic] })
  }

  return (
    <Card className="max-sm:[--card-spacing:--spacing(3)]">
      <CardContent className="py-3 space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <h3 className="text-[15px] font-semibold">통합 리포트 · {topic}</h3>
          {display?.created_at && (
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {md(display.created_at)} 작성{versionNo != null && versionNo > 0 && versionNo <= versions.length ? ` · 버전 ${versionNo}` : ""}
            </span>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {display?.id != null && (
              <SaveButton
                kind="report"
                refId={String(display.id)}
                url={`/report?topic=${encodeURIComponent(topic)}&v=${display.id}`}
                title={display.title || `${topic} 리포트`}
                subtitle={display.created_at ? display.created_at.slice(0, 10) : topic}
              />
            )}
            {!loading && (
              <Button size="sm" variant={display ? "outline" : "default"} className="h-7"
                onClick={() => run(!!display)}>
                <FileText className="h-3.5 w-3.5" /> {display ? "다시 생성" : "리포트 생성"}
              </Button>
            )}
          </div>
        </div>
        {loading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            내러티브 취합 → 종목 재분석 → 리포트 종합 중… (연쇄 LLM, 수 분)
          </div>
        )}
        {failed && <EmptyState message="리포트를 생성하지 못했습니다 — 잠시 후 다시 시도." />}
        {viewingOld && (
          <div className="flex items-center gap-2 rounded-md bg-muted/40 px-2.5 py-1 text-[11px] text-muted-foreground">
            <History className="h-3 w-3" /> 과거 버전 열람 중{display?.created_at ? ` (${display.created_at.slice(0, 10)})` : ""}
            <button className="ml-auto text-primary hover:underline" onClick={() => setVersionId(null)}>최신으로</button>
          </div>
        )}
        {display?.answer && display.created_at && <SinceLine stocks={display.stocks} topPick={display.top_pick} createdAt={display.created_at} />}
        {display?.answer && body && (
          <div className="space-y-3">
              {display.stocks.length > 0 && (
                <ReportCharts stocks={display.stocks} topPick={display.top_pick} />
              )}
              {display.title && <h3 className="text-lg font-bold leading-snug">{display.title}</h3>}
              <Markdown>{body.head}</Markdown>
              {body.rest && (
                <Collapsible className="border-t pt-2">
                  <CollapsibleTrigger className="group/rest flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">
                    <ChevronDown className="h-3.5 w-3.5 transition-transform group-data-[state=closed]/rest:-rotate-90" />
                    {reportSectionNames(body.rest).join(" · ")} 펼치기
                  </CollapsibleTrigger>
                  <CollapsibleContent className="pt-2"><Markdown>{body.rest}</Markdown></CollapsibleContent>
                </Collapsible>
              )}
              {display.stocks.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 border-t pt-2 text-[11px]">
                  <span className="text-muted-foreground">분석 종목</span>
                  {display.stocks.map((s) => (
                    <span key={s.code} className="inline-flex items-center gap-1">
                      {s.code === display.top_pick && (
                        <Badge className="text-[9px] bg-primary text-primary-foreground">Top-pick</Badge>
                      )}
                      <Link to={`/analyze/${s.code}/summary`} className={cn("hover:underline", s.code === display.top_pick ? "text-primary font-semibold" : "text-primary")}>{s.name}</Link>
                      {s.rating && (
                        <Badge variant="outline" className={cn("text-[9px]", RATING_CLS[ratingTone(s.rating)])}>{ratingLabel(s.rating)}</Badge>
                      )}
                      {(s.upside_pct != null || s.downside_pct != null) && (
                        <span className="text-[9px] text-muted-foreground tabular-nums">
                          {s.upside_pct != null ? `상방 +${Math.round(s.upside_pct)}%` : ""}
                          {s.upside_pct != null && s.downside_pct != null ? " / " : ""}
                          {s.downside_pct != null ? `하방 ${Math.round(s.downside_pct)}%` : ""}
                        </span>
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
                      {display.debate.bull && <div className="rounded-md border border-up/30 bg-up/5 px-2.5 py-1.5"><span className="font-semibold text-up">강세 (Bull)</span><div className="text-muted-foreground whitespace-pre-wrap mt-0.5">{relabelRatings(display.debate.bull)}</div></div>}
                      {display.debate.bear && <div className="rounded-md border border-down/30 bg-down/5 px-2.5 py-1.5"><span className="font-semibold text-down">약세 (Bear)</span><div className="text-muted-foreground whitespace-pre-wrap mt-0.5">{relabelRatings(display.debate.bear)}</div></div>}
                      {display.debate.fundamental && <p className="text-muted-foreground"><span className="font-medium text-foreground">펀더:</span> {relabelRatings(display.debate.fundamental)}</p>}
                      {display.debate.technical && <p className="text-muted-foreground"><span className="font-medium text-foreground">기술:</span> {relabelRatings(display.debate.technical)}</p>}
                      {display.debate.sentiment && <p className="text-muted-foreground"><span className="font-medium text-foreground">수급:</span> {relabelRatings(display.debate.sentiment)}</p>}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              )}
              {versions.length > 1 && (
                <Collapsible className="border-t pt-2">
                  <CollapsibleTrigger className="group/hist flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
                    <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/hist:rotate-180" />
                    이전 버전 {versions.length}개
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="space-y-1 pt-2">
                      {versions.map((v, i) => (
                        <button key={v.id} onClick={() => setVersionId(i === 0 ? null : v.id)}
                          className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[11px] hover:bg-muted/60",
                            (versionId === v.id || (i === 0 && versionId == null)) && "bg-muted/50")}>
                          <span className="text-muted-foreground tabular-nums shrink-0">{v.created_at.slice(0, 10)}</span>
                          {i === 0 && <Badge variant="secondary" className="text-[9px]">최신</Badge>}
                          <span className="truncate">{v.title ?? "(제목 없음)"}</span>
                        </button>
                      ))}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              )}
              <div className="text-[10px] text-muted-foreground/70 border-t pt-2">
                {display.cached && display.created_at ? `저장분 ${md(display.created_at)}` : "방금 생성"}
              </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** 작성 이후 변화 한 줄 — Top-pick 주가·12M 선행 PER의 작성일 → 최신(관측, 판정 아님). 자료가 없으면 줄을 그리지 않는다 */
function SinceLine({ stocks, topPick, createdAt }: { stocks: ReportResult["stocks"]; topPick?: string | null; createdAt: string }) {
  const top = stocks.find((s) => s.code === topPick) ?? stocks[0]
  const prices = useReportPrices(top?.code)
  const per = useReportFwdPer(top?.code)
  if (!top) return null
  const p = sinceChange((prices.data?.items ?? []).map((x) => ({ date: x.trade_date, value: x.close })), createdAt)
  const e = sinceChange((per.data?.items ?? []).filter((x) => x.fwd_per != null).map((x) => ({ date: x.date, value: x.fwd_per })), createdAt)
  if (!p && !e) return null
  return (
    <p className="bg-muted/40 px-3 py-2 text-[13px]" data-report-since>
      작성 이후 {top.name}
      {p && <> <span className={cn("tabular-nums", p.pct > 0 ? "text-up" : p.pct < 0 ? "text-down" : "")}>{formatPercent(p.pct)}</span>
        <span className="tabular-nums text-muted-foreground">({formatStockPrice(p.from)} → {formatStockPrice(p.to)})</span></>}
      {e && <> · 선행 PER <span className="tabular-nums">{formatPer(e.from)} → {formatPer(e.to)}</span></>}
    </p>
  )
}
