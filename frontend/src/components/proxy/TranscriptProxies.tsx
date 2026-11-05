import { Link } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Activity, ChevronDown, TrendingUp, TrendingDown, Minus, FileText } from "lucide-react"
import api from "@/api/client"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"

/**
 * 컨콜에서 뽑은 지표 (D-061 stage 4, 옛 탐색 › 컨콜 '프록시' 보기) — 컨콜에서 추출한 선행지표 시계열.
 * 리포트 핵심질문(D-049)이 던지는 "무엇을 지켜봐야 하나"를 실데이터로 추적한다.
 * 4f단계(ia-redesign §4.10)에서 Thesis › 내 판단 '지표 보드' 아래로 옮겼다 — 지표가 많아 접어서 둔다.
 */
interface Obs { observed_at: string | null; value_num: number | null; value_text: string | null; direction: string | null; ticker: string | null; transcript_id: number | null }
interface ProxyRow { id: number; key: string; label: string; unit: string | null; tickers: string | null; latest: Obs | null; series: Obs[] }

function DirIcon({ d }: { d: string | null }) {
  if (d === "up") return <TrendingUp className="h-3.5 w-3.5 text-up" />
  if (d === "down") return <TrendingDown className="h-3.5 w-3.5 text-down" />
  return <Minus className="h-3.5 w-3.5 text-muted-foreground" />
}

export function TranscriptProxies() {
  const qc = useQueryClient()
  const { data: proxies = [], isLoading, isError, refetch } = useQuery(
    apiQuery<ProxyRow[]>({ key: ["spine", "transcript", "proxies"], url: "/api/spine/transcript/proxies", staleTime: STALE.short }),
  )
  const extract = useMutation({
    mutationFn: () => api.post("/api/spine/transcript/proxies/extract", null, { timeout: 600_000 }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "transcript", "proxies"] }),
  })

  if (isLoading) return <Skeleton className="h-16 w-full rounded-card" />
  if (isError) return <ErrorState message="컨콜 지표를 불러오지 못했습니다." onRetry={() => void refetch()} />

  const totalObs = proxies.reduce((s, p) => s + p.series.length, 0)

  return (
    <Collapsible className="space-y-3" id="transcript-proxies">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="group h-auto gap-1.5 px-0 text-[15px] font-semibold hover:bg-transparent">
            <ChevronDown className="size-4 transition-transform group-data-[state=closed]:-rotate-90" />
            컨콜에서 뽑은 지표
            <span className="font-normal tabular-nums text-muted-foreground">{proxies.length}개 · 관측 {totalObs}건</span>
          </Button>
        </CollapsibleTrigger>
        <span className="flex items-center gap-1">
          <InfoTip label="컨콜에서 뽑은 지표 설명">컨콜 녹취록에서 추출한 선행지표입니다. 리포트 핵심 질문이 지켜보라는 값들이며, 옛 탐색 › 컨콜의 '프록시' 보기를 여기로 옮겼습니다.</InfoTip>
          <Button size="sm" variant="outline" onClick={() => extract.mutate()} disabled={extract.isPending}>
            <Activity className="h-3.5 w-3.5" /> {extract.isPending ? "추출 중… (수 분)" : "프록시 추출 실행"}
          </Button>
        </span>
      </div>
      <CollapsibleContent>

      {proxies.length === 0 ? (
        <EmptyState message="등록된 프록시가 없습니다 — 추출 실행 시 기본 세트가 생성됩니다." />
      ) : totalObs === 0 && !extract.isPending ? (
        <EmptyState message="아직 추출된 관측치가 없습니다 — 컨콜 수집 후 '프록시 추출 실행'을 누르세요." />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {proxies.map((p) => (
            <Card key={p.id}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  {p.label}
                  {p.unit && <Badge variant="secondary" className="text-[10px] font-normal">{p.unit}</Badge>}
                  {p.latest && <span className="ml-auto"><DirIcon d={p.latest.direction} /></span>}
                </CardTitle>
                {p.tickers && <div className="text-[10px] text-muted-foreground">{p.tickers}</div>}
              </CardHeader>
              <CardContent>
                {p.series.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-2">관측치 없음</p>
                ) : (
                  <ul className="space-y-1.5">
                    {[...p.series].reverse().slice(0, 8).map((o, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs">
                        <DirIcon d={o.direction} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                            <span className="font-medium text-foreground">{o.ticker}</span>
                            {o.observed_at && <span className="tabular-nums">{o.observed_at.slice(0, 10)}</span>}
                            {o.transcript_id && (
                              <Link to={`/follow/transcripts?t=${o.transcript_id}`} className="hover:text-foreground">
                                <FileText className="h-3 w-3" />
                              </Link>
                            )}
                          </div>
                          <p className="text-muted-foreground leading-snug">{o.value_text}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      </CollapsibleContent>
    </Collapsible>
  )
}
