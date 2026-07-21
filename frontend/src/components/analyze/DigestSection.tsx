import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ChevronDown, Lightbulb, RefreshCw } from "lucide-react"
import { Markdown } from "@/components/shared/Markdown"
import api from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Expandable } from "@/components/shared/Expandable"
import { ProposalPanel } from "@/components/shared/ProposalPanel"
import { cn } from "@/lib/utils"

/**
 * 언급 다이제스트 (1D · 7D) — 언급 탭에서 종목 홈으로 이관 (P2-1 후속).
 * AI 브리프의 '원재료' 위치: 브리프가 종합이고, 이건 기간별 원요약.
 * 진입 시 자동 생성 없음 — 우측 새로고침(⟳)으로 온디맨드 생성(당일 생성분은 덮어쓰기).
 */

interface DigestItem {
  period: string
  period_start: string
  digest: string | null
  insights: string | null
  doc_count: number | null
  model: string | null
}

export default function DigestSection({ stockCode, stack = false }: { stockCode: string; stack?: boolean }) {
  return (
    <div className={stack ? "space-y-4" : "grid grid-cols-1 lg:grid-cols-2 gap-4 items-start"}>
      <DigestCard stockCode={stockCode} period="1d" title="1D 요약" />
      <DigestCard stockCode={stockCode} period="7d" title="7D 요약" />
    </div>
  )
}

function DigestCard({ stockCode, period, title }: { stockCode: string; period: "1d" | "7d"; title: string }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ["spine", "digests", stockCode, period],
    queryFn: async () =>
      (await api.get("/api/spine/digests", { params: { stock: stockCode, period } })).data as {
        items: DigestItem[]
      },
    staleTime: 5 * 60_000,
  })

  const compute = useMutation({
    mutationFn: async () =>
      (await api.post("/api/spine/digests/compute", null, { params: { stock: stockCode, period } }))
        .data as { status: string },
    onSuccess: (d) => {
      if (d.status === "ok") {
        toast.success(`${title} 갱신 완료`)
        qc.invalidateQueries({ queryKey: ["spine", "digests", stockCode, period] })
      } else if (d.status === "empty") {
        toast.info(period === "1d" ? "오늘 수집된 언급이 없어 생성할 내용이 없습니다" : "요약할 최근 데이터가 없습니다")
      } else {
        toast.error("LLM 엔진이 연결되어 있지 않습니다")
      }
    },
    onError: () => toast.error(`${title} 생성 실패 — 잠시 후 다시 시도`),
  })

  const items = data?.items ?? []
  const latest = items[0]
  const archive = items.slice(1)

  return (
    <ProposalPanel
      title={title}
      subtitle={latest ? `${latest.period_start} 기준 · ${latest.doc_count ?? "-"}건` : undefined}
      maxHeight="55vh"
      className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]"
      contentClassName="space-y-3"
      action={
        <Button variant="ghost" size="icon" className="size-7"
          onClick={() => compute.mutate()} disabled={compute.isPending}
          aria-label="새로고침 — 지금 다시 생성" title="지금 다시 생성 (당일 생성분은 덮어씀)">
          <RefreshCw className={cn("h-3.5 w-3.5", compute.isPending && "animate-spin")} />
        </Button>
      }
    >
      {compute.isPending && (
        <p className="text-xs text-muted-foreground py-1">요약을 생성하는 중… (수십 초)</p>
      )}
      {!latest && !compute.isPending ? (
        <p className="text-xs text-muted-foreground py-2">
          아직 요약이 없습니다 — 우측 ⟳ 로 생성하세요. (언급 수집 시 30분 주기로도 생성됩니다)
        </p>
      ) : latest ? (
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
                지난 요약 {archive.length}건
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
      ) : null}
    </ProposalPanel>
  )
}
