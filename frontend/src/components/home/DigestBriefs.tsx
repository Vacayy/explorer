// Home 종목 요약 카드 (D-124) — 가장 최근 닫힌 구간의 언급 상위 5종목 요약을 **내용까지**.
// 전엔 'AI가 최근 만든 것'에 "OO 1D 요약"이라는 알림만 떠서 내용을 보려면 종목 페이지로 들어가야 했다.
import { useState } from "react"
import { Link } from "react-router-dom"
import { ChevronDown, LineChart } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { Markdown } from "@/components/shared/Markdown"
import { cn } from "@/lib/utils"

interface DigestBrief {
  name: string
  stock_code: string | null
  period: string
  period_start: string
  digest: string
  insights: string | null
  doc_count: number | null
}

/** 마크다운 본문에서 첫 제목·문장을 뽑아 접힌 상태의 한 줄로 */
function gist(md: string): string {
  const line = md
    .split("\n")
    .map((l) => l.replace(/^#+\s*/, "").trim())
    .find((l) => l.length > 8 && !l.startsWith("|"))
  return line ?? md.slice(0, 80)
}

export function DigestBriefs() {
  const [openIdx, setOpenIdx] = useState<number | null>(null)
  const { data, isLoading } = useQuery(
    apiQuery<DigestBrief[]>({
      key: ["spine", "home", "digests"],
      url: "/api/spine/home/digests?period=1d&limit=5",
      staleTime: STALE.short,
    }),
  )

  if (isLoading) return <Skeleton className="h-40 w-full rounded-xl" />
  const items = data ?? []
  if (items.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <LineChart className="h-4 w-4 text-muted-foreground" /> 종목 요약
        </CardTitle>
        <span className="text-[11px] text-muted-foreground">
          {items[0].period_start} · 언급 상위 {items.length}종목
        </span>
      </CardHeader>
      <CardContent className="divide-y py-0">
        {items.map((d, i) => (
          <Collapsible
            key={`${d.name}-${d.period_start}`}
            open={openIdx === i}
            onOpenChange={(o) => setOpenIdx(o ? i : null)}
          >
            <CollapsibleTrigger asChild>
              <button className="group w-full py-2.5 text-left">
                <div className="flex items-center gap-2">
                  <span className="shrink-0 text-sm font-medium group-hover:underline">{d.name}</span>
                  {d.doc_count != null && (
                    <Badge variant="outline" className="shrink-0 text-[10px]">문서 {d.doc_count}</Badge>
                  )}
                  <ChevronDown
                    className={cn("ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
                      openIdx === i && "rotate-180")}
                  />
                </div>
                {/* 접힌 상태에서도 무슨 얘기인지 — 새로운 시각이 있으면 그것을 우선 */}
                <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                  {d.insights ? (
                    <><span className="text-hypothesis">새로운 시각 </span>{d.insights}</>
                  ) : (
                    gist(d.digest)
                  )}
                </p>
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="pb-3">
                <Markdown>{d.digest}</Markdown>
                {/* 국내 상장사는 종목 도시에, 종목코드 없는 해외·비상장은 기업 프로필로 (D-124).
                    상한 5는 국적 혼합이라 링크가 한쪽만 있으면 절반이 막다른 길이 된다 */}
                <div className="mt-1.5 text-right">
                  <Link
                    to={d.stock_code
                      ? `/analyze/${d.stock_code}/mentions`
                      : `/company?name=${encodeURIComponent(d.name)}`}
                    className="text-[11px] text-muted-foreground hover:text-primary hover:underline"
                  >
                    언급 전체 보기 →
                  </Link>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>
        ))}
      </CardContent>
    </Card>
  )
}
