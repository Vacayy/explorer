import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import ReactMarkdown from "react-markdown"
import { ChevronDown, ChevronUp, Lightbulb } from "lucide-react"
import api from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * 언급 다이제스트 (1D · 7D 롤링, 2열) — 언급 탭에서 종목 홈으로 이관 (P2-1 후속).
 * AI 브리프의 '원재료' 위치: 브리프가 종합이고, 이건 기간별 원요약.
 */

interface DigestItem {
  period: string
  period_start: string
  digest: string | null
  insights: string | null
  doc_count: number | null
  model: string | null
}

export default function DigestSection({ stockCode }: { stockCode: string }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
      <DigestCard stockCode={stockCode} period="1d" title="1D 요약" />
      <DigestCard stockCode={stockCode} period="7d" title="7D 롤링 요약" />
    </div>
  )
}

function DigestCard({ stockCode, period, title }: { stockCode: string; period: "1d" | "7d"; title: string }) {
  const [showArchive, setShowArchive] = useState(false)
  const { data } = useQuery({
    queryKey: ["spine", "digests", stockCode, period],
    queryFn: async () =>
      (await api.get("/api/spine/digests", { params: { stock: stockCode, period } })).data as {
        items: DigestItem[]
      },
    staleTime: 5 * 60_000,
  })

  const items = data?.items ?? []
  const latest = items[0]
  const archive = items.slice(1)

  return (
    <Card className="border-l-2 border-l-hypothesis flex flex-col">
      <CardHeader className="pb-2 flex-row items-baseline gap-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {latest && (
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
            {latest.period_start} 기준 · {latest.doc_count ?? "-"}건
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {!latest ? (
          <p className="text-xs text-muted-foreground py-2">
            아직 요약이 없습니다. 언급이 수집되면 30분 주기로 생성됩니다.
          </p>
        ) : (
          <>
            {latest.insights && (
              <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
                <Lightbulb className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
                <p className="text-xs"><span className="font-semibold text-hypothesis">새로운 시각</span> {latest.insights}</p>
              </div>
            )}
            <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_h3]:text-[13px] [&_h3]:mt-2.5 [&_h3]:mb-1 [&_p]:my-1.5">
              <ReactMarkdown>{latest.digest ?? ""}</ReactMarkdown>
            </div>
            <div className="text-right">
              <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                AI 요약 · {latest.model}
              </Badge>
            </div>

            {archive.length > 0 && (
              <div className="border-t pt-2">
                <button onClick={() => setShowArchive(!showArchive)}
                  className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
                  {showArchive ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  지난 요약 {archive.length}건
                </button>
                {showArchive && (
                  <div className="space-y-3 pt-2">
                    {archive.map((d) => (
                      <div key={d.period_start} className="rounded-md border px-3 py-2">
                        <div className="text-[11px] text-muted-foreground tabular-nums mb-1">
                          {d.period_start} · 문서 {d.doc_count ?? "-"}건
                        </div>
                        {d.insights && <p className="text-[11px] text-hypothesis mb-1">💡 {d.insights}</p>}
                        <div className="prose prose-sm dark:prose-invert max-w-none text-xs [&_p]:my-1">
                          <ReactMarkdown>{d.digest ?? ""}</ReactMarkdown>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
