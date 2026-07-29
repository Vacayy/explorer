import { useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ChevronDown, Lightbulb, Loader2, RefreshCw } from "lucide-react"
import { Markdown } from "@/components/shared/Markdown"
import api from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Expandable } from "@/components/shared/Expandable"
import { ProposalPanel } from "@/components/shared/ProposalPanel"
import { cn } from "@/lib/utils"

/**
 * 언급 다이제스트 (1D 오늘 · 1W 주간 · 1M 월간) — 캘린더 기준(비롤링, D-085).
 * 진입 시 자동 catch-up: 오래 밀렸으면 과거 월 1M, 이번 달 주 1W, 오늘 1D를 소급 생성(백그라운드).
 * 매일 눌러야 하던 불편 제거 — 들어오면 밀린 만큼 알아서 채운다(멱등, 재진입 무비용).
 */

interface DigestItem {
  period: string
  period_start: string
  digest: string | null
  insights: string | null
  doc_count: number | null
  model: string | null
}

const caughtUp = new Set<string>() // 세션 내 종목별 1회 catch-up 가드 (재진입 스팸 방지)

export default function DigestSection({ stockCode, stack = false }: { stockCode: string; stack?: boolean }) {
  const qc = useQueryClient()
  const catchup = useMutation({
    mutationFn: async () =>
      (await api.post("/api/spine/digests/catchup", null, { params: { stock: stockCode }, timeout: 600_000 }))
        .data as { status: string; monthly: number; weekly: number; daily: number },
    onSuccess: (d) => {
      if (d.status !== "ok") return
      ;(["1d", "1w", "1m"] as const).forEach((p) =>
        qc.invalidateQueries({ queryKey: ["spine", "digests", stockCode, p] }))
      const n = (d.monthly || 0) + (d.weekly || 0) + (d.daily || 0)
      if (n) toast.success(`요약 ${n}건 갱신`)
    },
    onError: () => toast.error("요약 업데이트 실패 — 잠시 후 다시 시도"),
  })

  // 진입 시 자동 catch-up (백그라운드, 세션당 종목 1회 — 재진입은 idempotent라도 스팸 방지)
  useEffect(() => {
    if (caughtUp.has(stockCode)) return
    caughtUp.add(stockCode)
    catchup.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stockCode])

  return (
    <div className="space-y-4">
      {catchup.isPending && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 밀린 요약을 채우는 중… (오래 안 봤으면 수십 초~수 분)
        </div>
      )}

      <div className={stack ? "space-y-4" : "grid grid-cols-1 lg:grid-cols-2 gap-4 items-start"}>
        <PeriodBlock stockCode={stockCode} period="1d" title="오늘 (1D)" />
        <PeriodBlock stockCode={stockCode} period="1w" title="주간 (1W)" />
      </div>
      <PeriodBlock stockCode={stockCode} period="1m" title="월간 (1M)" />

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" className="text-xs text-muted-foreground"
          onClick={() => catchup.mutate()} disabled={catchup.isPending}
          title="지금 밀린 요약을 다시 채웁니다">
          <RefreshCw className={cn("h-3.5 w-3.5", catchup.isPending && "animate-spin")} /> 지금 업데이트
        </Button>
      </div>
    </div>
  )
}

const SUBTITLE: Record<string, string> = { "1d": "당일", "1w": "그 주 월요일", "1m": "그 달 1일" }

function PeriodBlock({ stockCode, period, title }: { stockCode: string; period: "1d" | "1w" | "1m"; title: string }) {
  const { data } = useQuery({
    queryKey: ["spine", "digests", stockCode, period],
    queryFn: async () =>
      (await api.get("/api/spine/digests", { params: { stock: stockCode, period } })).data as { items: DigestItem[] },
    staleTime: 5 * 60_000,
  })

  const items = data?.items ?? []
  const latest = items[0]
  const archive = items.slice(1)

  return (
    <ProposalPanel
      title={title}
      subtitle={latest ? `${latest.period_start} 기준(${SUBTITLE[period]}) · ${latest.doc_count ?? "-"}건` : undefined}
      maxHeight="55vh"
      className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]"
      contentClassName="space-y-3"
    >
      {!latest ? (
        <p className="text-xs text-muted-foreground py-2">
          아직 {title} 요약이 없습니다 — 진입 시 자동 생성되며, 이 구간에 수집된 언급이 없으면 비어 있습니다.
        </p>
      ) : (
        <>
          {latest.insights && (
            <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
              <Lightbulb className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
              <p className="text-xs line-clamp-3"><span className="font-semibold text-hypothesis">새로운 시각</span> {latest.insights}</p>
            </div>
          )}
          <Expandable collapsedHeight={180}>
            <Markdown>{latest.digest ?? ""}</Markdown>
          </Expandable>
          <div className="text-right">
            <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
              AI 요약 · {latest.model}
            </Badge>
          </div>

          {archive.length > 0 && (
            <Collapsible className="border-t pt-2">
              <CollapsibleTrigger className="group/archive flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
                <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/archive:rotate-180" />
                지난 {title} {archive.length}건
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="space-y-3 pt-2">
                  {archive.map((d) => (
                    <div key={d.period_start} className="rounded-md border px-3 py-2">
                      <div className="text-[11px] text-muted-foreground tabular-nums mb-1">
                        {d.period_start} · 문서 {d.doc_count ?? "-"}건
                      </div>
                      {d.insights && <p className="text-[11px] text-hypothesis mb-1">💡 {d.insights}</p>}
                      <Markdown className="text-xs">{d.digest ?? ""}</Markdown>
                    </div>
                  ))}
                </div>
              </CollapsibleContent>
            </Collapsible>
          )}
        </>
      )}
    </ProposalPanel>
  )
}
