import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Users } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import { usePeopleDirectory } from "@/hooks/usePeople"
import { formatNumber, formatRelativeTime } from "@/utils/format"
import { cn } from "@/lib/utils"
import type { PeopleSort } from "@/types"

/**
 * /people — 인물 디렉토리 (탐색의 발견 표면).
 * 기본은 '이번 주 떠오른 사람'(최근 7일 − 직전 7일 언급) 순. 언급 1건짜리 롱테일은 스위치로만 보인다(팔로우 인물은 늘 보인다).
 * URL: days(0·30·7) · sort(surge 기본·total·recent) · tail=1.
 */

const PERIOD_FILTERS = [
  { key: 0, label: "전체" },
  { key: 30, label: "최근 30일" },
  { key: 7, label: "최근 7일" },
] as const
const SORTS: { key: PeopleSort; label: string }[] = [
  { key: "surge", label: "7일 급상승" },
  { key: "total", label: "언급 많은 순" },
  { key: "recent", label: "최근 언급 순" },
]
const PAGE = 100

const deltaTone = (d: number) => d > 0 ? "text-up" : d < 0 ? "text-down" : "text-muted-foreground"
const signed = (d: number) => `${d > 0 ? "+" : ""}${formatNumber(d)}`

export default function PeopleDirectoryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const days = Number(searchParams.get("days") ?? "0")
  const sortParam = searchParams.get("sort")
  const sort: PeopleSort = sortParam === "total" || sortParam === "recent" ? sortParam : "surge"
  const tail = searchParams.get("tail") === "1"
  const [shown, setShown] = useState(PAGE)
  const { data, isLoading, isError, refetch, isPlaceholderData } = usePeopleDirectory({ days, sort, tail })
  const setParam = (k: string, v: string | null) => {
    setShown(PAGE)
    setSearchParams((p) => {
      const n = new URLSearchParams(p)
      if (v) n.set(k, v); else n.delete(k)
      return n
    }, { replace: true })
  }

  if (isLoading) return <PeopleSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  return (
    <PageContainer gap="sm">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Users className="h-5 w-5 text-muted-foreground" /> 인물
        </h2>
        <span className="text-xs text-muted-foreground tabular-nums">
          {formatNumber(data.total)}명 언급됨{data.hidden_tail > 0 && ` · 언급 1건 ${formatNumber(data.hidden_tail)}명 숨김`}
        </span>
        <span className="ml-auto flex gap-1">
          {PERIOD_FILTERS.map((f) => (
            <Badge
              key={f.key}
              variant={days === f.key ? "default" : "outline"}
              className="cursor-pointer select-none text-xs"
              onClick={() => setParam("days", f.key ? String(f.key) : null)}
            >
              {f.label}
            </Badge>
          ))}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroup type="single" size="sm" variant="outline" value={sort} aria-label="정렬"
          onValueChange={(v) => v && setParam("sort", v === "surge" ? null : v)}>
          {SORTS.map((s) => <ToggleGroupItem key={s.key} value={s.key} className="px-3 text-xs">{s.label}</ToggleGroupItem>)}
        </ToggleGroup>
        <div className="flex items-center gap-2">
          <Switch id="people-tail" checked={tail} onCheckedChange={(on) => setParam("tail", on ? "1" : null)} />
          <Label htmlFor="people-tail" className="text-xs font-normal text-muted-foreground">언급 1건도 보기</Label>
        </div>
        {sort === "surge" && <span className="text-[11px] text-muted-foreground">최근 7일 언급 − 그 전 7일 언급</span>}
      </div>

      {data.items.length === 0 ? (
        <EmptyState message="해당 기간에 언급된 인물이 없습니다. 수집이 쌓이면 자동으로 나타납니다." />
      ) : (
        <Card className={cn(isPlaceholderData && "opacity-60")}>
          <CardContent className="divide-y">
            {data.items.slice(0, shown).map((p) => (
              <div key={p.entity_id} className="py-2.5 space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <Link
                    to={`/person?name=${encodeURIComponent(p.name)}`}
                    className="whitespace-nowrap font-semibold text-sm hover:underline hover:text-primary"
                  >
                    {p.name}
                  </Link>
                  {p.following && (
                    <Badge variant="outline" className="text-[9px] text-primary border-primary/40">팔로우 중</Badge>
                  )}
                  <span className="whitespace-nowrap text-[11px] text-muted-foreground tabular-nums">
                    7일 {formatNumber(p.mentions_7d)}건
                    <span className={cn("ml-1", deltaTone(p.delta_7d))}>({signed(p.delta_7d)})</span>
                    {" · "}{days ? `${days}일` : "누적"} {formatNumber(p.doc_count)}건
                  </span>
                  <span className="flex w-full gap-1 md:ml-auto md:w-auto">
                    {p.top_stocks.map((s) => (
                      <Badge key={s} variant="secondary" className="text-[10px] font-normal">{s}</Badge>
                    ))}
                  </span>
                </div>
                {p.last_doc_title && (
                  <div className="flex items-baseline gap-2">
                    <Link
                      to={p.last_doc_id ? `/doc/${p.last_doc_id}` : "#"}
                      className={cn("text-xs text-muted-foreground truncate", p.last_doc_id && "hover:underline hover:text-foreground")}
                    >
                      최근 언급 — {p.last_doc_title}
                    </Link>
                    <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
                      {formatRelativeTime(p.last_doc_at ?? "")}
                    </span>
                  </div>
                )}
              </div>
            ))}
            {data.items.length > shown && (
              <div className="pt-3 text-center">
                <Button variant="outline" size="sm" onClick={() => setShown((n) => n + PAGE)}>
                  더 보기 ({formatNumber(data.items.length - shown)}명 남음)
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </PageContainer>
  )
}

function PeopleSkeleton() {
  return (
    <PageContainer gap="sm">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-96 w-full rounded-xl" />
    </PageContainer>
  )
}
