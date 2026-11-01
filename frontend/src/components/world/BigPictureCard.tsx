import { useState } from "react"
import { ChevronDown, Globe2 } from "lucide-react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState, ErrorState } from "@/components/shared/ErrorState"
import { Expandable } from "@/components/shared/Expandable"
import { Markdown } from "@/components/shared/Markdown"
import { useBigPicture } from "@/hooks/useWorld"
import { cn } from "@/lib/utils"
import { formatDbRelative } from "@/utils/format"
import type { WorldMega } from "@/types"

/** 엮인 서사 한 편 — 제목 + 관통하는 주제 칩. 펼치면 본문 */
function MegaRow({ m }: { m: WorldMega }) {
  const [open, setOpen] = useState(false)
  return <Collapsible open={open} onOpenChange={setOpen} className="space-y-1.5">
    <div className="flex items-start gap-2">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="icon-xs" aria-label={open ? "본문 접기" : "본문 펼치기"} className="mt-0.5">
          <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
        </Button>
      </CollapsibleTrigger>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-semibold leading-snug">{m.title ?? m.name}</p>
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-0.5 text-[11px] text-muted-foreground">{m.members.length}개 서사를 관통</span>
          {m.members.map(t => <Badge key={t} asChild variant="secondary" className="text-[10px]">
            <Link to={`/narrative?topic=${encodeURIComponent(t)}`}>{t}</Link>
          </Badge>)}
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{formatDbRelative(m.created_at)}</span>
        </div>
      </div>
    </div>
    <CollapsibleContent className="pl-8">{m.narrative && <Markdown>{m.narrative}</Markdown>}</CollapsibleContent>
  </Collapsible>
}

/**
 * 이번 주 큰 그림 — 살아 있는 엮인 서사(메가) + 저장된 세계관 브리핑을 한 카드로.
 * 표시만 한다: 이 카드는 아무것도 생성하지 않는다(세계관 갱신은 그래프 › 검증 지식 화면의 기존 경로).
 */
export function BigPictureCard() {
  const q = useBigPicture()
  const wv = q.data?.worldview
  return <Card className="bg-[color-mix(in_srgb,var(--primary)_4%,var(--card))]">
    <CardHeader className="flex flex-row flex-wrap items-baseline gap-2 pb-2">
      <CardTitle className="text-sm">이번 주 큰 그림</CardTitle>
      <span className="text-[11px] text-muted-foreground">여러 서사를 관통하는 줄기와 자리 잡은 전제</span>
      <Badge variant="outline" className="ml-auto text-[10px] font-normal text-hypothesis border-hypothesis/40">AI 종합 · 검증 필요</Badge>
    </CardHeader>
    <CardContent className="space-y-4">
      {q.isLoading ? <div className="space-y-2"><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
        : q.isError ? <ErrorState message="큰 그림을 불러오지 못했습니다." onRetry={() => void q.refetch()} />
        : !q.data?.mega.length && !wv?.briefing ? <EmptyState message="아직 엮인 서사와 세계관 브리핑이 없습니다. 서사가 쌓이면 주 1회 만들어집니다." />
        : <>
          {q.data!.mega.length > 0 && <div className="space-y-3">{q.data!.mega.map(m => <MegaRow key={m.id} m={m} />)}</div>}
          {wv?.briefing && <section className="space-y-2 border-t pt-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="flex items-center gap-1.5 text-sm font-medium"><Globe2 aria-hidden="true" className="size-4 text-hypothesis" />세계관 브리핑</h3>
              <span className="text-[11px] text-muted-foreground tabular-nums">{formatDbRelative(wv.created_at)} 저장</span>
              {wv.stale && <span className="text-[11px] text-chart-warning">이후 지식·관측이 바뀌었습니다 — <Link to="/knowledge" className="underline">그래프 › 검증 지식</Link>에서 갱신</span>}
            </div>
            <Expandable collapsedHeight={160}><Markdown>{wv.briefing}</Markdown></Expandable>
          </section>}
        </>}
    </CardContent>
  </Card>
}
