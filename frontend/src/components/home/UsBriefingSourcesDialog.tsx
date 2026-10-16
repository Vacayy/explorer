import { useState } from "react"
import { ExternalLink, ListTree } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { formatNumber, formatRelativeTime } from "@/utils/format"
import { useUsBriefingSources } from "@/hooks/useUsBriefing"
import type { UsBriefingSourceItem } from "@/types"

/**
 * 미국장 브리핑 '소스 관리' (docs/specs/us-briefing.md) — 브리핑이 쓰는 출처와 각 출처의 최근 수집 상태.
 * 읽기 전용: 채널·피드 목록은 코드 상수(MACRO_CHANNELS·FEEDS)라 여기서 편집하지 않는다.
 */
export function UsBriefingSourcesDialog() {
  const [open, setOpen] = useState(false)
  const { data, isLoading, isError, refetch } = useUsBriefingSources(open)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-caption text-muted-foreground">
          <ListTree className="h-3.5 w-3.5" /> 소스 관리
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>브리핑 소스</DialogTitle>
          <DialogDescription>
            어젯밤 미국장 브리핑이 쓰는 출처와 최근 수집 상태입니다. 최근 2일 안에 자료가 없으면 ‘조용함’으로 표시합니다.
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full rounded-lg" />)}</div>
        ) : isError || !data ? (
          <ErrorState message="소스 목록을 불러올 수 없습니다." onRetry={() => refetch()} />
        ) : data.groups.length === 0 ? (
          <EmptyState message="등록된 소스가 없습니다." />
        ) : (
          <ScrollArea className="max-h-[65vh] pr-3">
            <div className="space-y-4">
              {data.groups.map((g) => (
                <section key={g.key}>
                  <div className="mb-1 flex items-baseline gap-2">
                    <h3 className="text-sm font-semibold">{g.label}</h3>
                    <span className="text-caption text-muted-foreground">{g.used_for}</span>
                    <span className="ml-auto text-caption tabular-nums text-muted-foreground">{g.items.length}개</span>
                  </div>
                  <ul className="divide-y rounded-lg border">
                    {g.items.map((it) => <SourceRow key={`${it.name}-${it.detail}`} item={it} />)}
                  </ul>
                </section>
              ))}
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  )
}

const STATUS = {
  ok: { label: "수집 중", cls: "text-primary border-primary/40" },
  quiet: { label: "조용함", cls: "text-chart-warning border-chart-warning/40" },
  off: { label: "꺼짐", cls: "text-muted-foreground" },
} as const

function SourceRow({ item }: { item: UsBriefingSourceItem }) {
  const st = STATUS[item.status]
  // 지표는 날짜만 있다 — 상대 시간으로 바꾸면 '어제'가 거래일인지 흐려진다
  const seen = !item.last_seen ? "자료 없음"
    : item.last_seen.length === 10 ? `${item.last_seen} 기준` : `최근 ${formatRelativeTime(item.last_seen)}`
  return (
    <li className="flex items-center gap-2 px-2.5 py-1.5 text-sm min-w-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 min-w-0">
          {item.url ? (
            <a href={item.url} target="_blank" rel="noreferrer" className="truncate font-medium hover:underline">{item.name}</a>
          ) : <span className="truncate font-medium">{item.name}</span>}
          {item.url && <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />}
        </div>
        {item.detail && <p className="truncate text-caption text-muted-foreground">{item.detail}</p>}
      </div>
      <div className="shrink-0 text-right text-caption text-muted-foreground tabular-nums">
        <div>{seen}</div>
        {item.recent_count != null && <div>24시간 {formatNumber(item.recent_count)}건</div>}
      </div>
      <Badge variant="outline" className={`shrink-0 text-caption ${st.cls}`}>{st.label}</Badge>
    </li>
  )
}
