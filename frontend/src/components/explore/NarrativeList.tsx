import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Sparkles } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { EmptyState } from "@/components/shared/ErrorState"
import { dbAgeDays, formatRelativeTime } from "@/utils/format"
import { cn } from "@/lib/utils"
import { BoundedArea } from "@/components/shared/Bounded"

/** SQLite UTC 시각("YYYY-MM-DD HH:MM:SS")을 상대 표기로 — Z 부착해 로컬 오파싱 방지(D-059). */
function relUpdated(iso: string | null): string {
  return iso ? formatRelativeTime(iso.replace(" ", "T") + "Z") : ""
}

/** 내러티브 카드 목록 — 신호 티저(limit)와 월드모델>내러티브 랜딩이 공유. */
export interface NarrativeItem {
  topic: string
  title: string | null
  summary: string | null
  category: string | null
  share_pct: number | null
  share_delta_pp: number | null
  is_new: boolean
  is_surging: boolean
  created_at: string | null
  drift_summary: string | null   // 이번 버전에서 무엇이 바뀌었나 한 줄 (D-123)
  version: number | null
}

/** 렌즈 카테고리 — NarrativePage LENS_LABEL과 동일 (category는 콤마 구분 렌즈 목록). */
const LENS: { value: string; label: string }[] = [
  { value: "macro", label: "매크로" },
  { value: "geopolitics", label: "지정학" },
  { value: "industry", label: "산업" },
  { value: "flow", label: "수급" },
  { value: "tech", label: "기술" },
  { value: "policy", label: "정책" },
]

type SortKey = "changed" | "latest" | "share" | "surge"
const SORT: { value: SortKey; label: string }[] = [
  { value: "changed", label: "변화순" },
  { value: "latest", label: "최신순" },
  { value: "share", label: "비중순" },
  { value: "surge", label: "급등순" },
]

/** 이 일수보다 오래된 서사는 기본으로 접고(목록 아래 토글), 보일 때도 흐리게 */
const STALE_DAYS = 30

const sortFns: Record<SortKey, (a: NarrativeItem, b: NarrativeItem) => number> = {
  // 변화순(D-123) — '무엇이 바뀌었나'가 있는 것을 위로. 다 읽을 수 없으니 변한 것만 훑게.
  changed: (a, b) => Number(!!b.drift_summary) - Number(!!a.drift_summary)
    || (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  latest: (a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  share: (a, b) => (b.share_pct ?? -1) - (a.share_pct ?? -1),
  surge: (a, b) => (b.share_delta_pp ?? -Infinity) - (a.share_delta_pp ?? -Infinity),
}

export function NarrativeList({
  limit,
  fold,
  empty = "hide",
  controls = false,
}: {
  limit?: number
  /** 처음엔 이만큼만 보이고 '더 보기'로 전부 펼친다(URL ?list=all) */
  fold?: number
  empty?: "hide" | "state"
  controls?: boolean
}) {
  const { data } = useQuery(
    apiQuery<{ items: NarrativeItem[] }>({
      key: ["spine", "narrative", "list"],
      url: "/api/spine/narrative/list",
      staleTime: STALE.medium,
    }),
  )
  const items = data?.items ?? []

  const [lenses, setLenses] = useState<string[]>([])
  const [sort, setSort] = useState<SortKey>("changed")   // 델타 우선 (D-123)
  // 오래된 서사 보기 — URL이 상태 소스(?old=1)
  const [params, setParams] = useSearchParams()
  const showOld = params.get("old") === "1"
  const expanded = params.get("list") === "all"
  const setShowOld = (on: boolean) => setParams(prev => { const next = new URLSearchParams(prev); if (on) next.set("old", "1"); else next.delete("old"); return next }, { replace: true, preventScrollReset: true })
  const isOld = (n: NarrativeItem) => dbAgeDays(n.created_at) > STALE_DAYS

  const filtered = useMemo(() => {
    if (!controls) return items   // 티저 등 — 백엔드 순서(급증 우선) 유지
    const picked = new Set(lenses)
    const matched = picked.size
      ? items.filter((n) => (n.category ?? "").split(",").some((c) => picked.has(c)))
      : items
    return [...matched].sort(sortFns[sort])
  }, [items, lenses, sort, controls])
  const oldCount = controls ? filtered.filter(isOld).length : 0
  const visible = controls && !showOld ? filtered.filter(n => !isOld(n)) : filtered

  if (items.length === 0) {
    return empty === "state"
      ? <EmptyState message="아직 생성된 내러티브가 없습니다 — 주목 주제가 쌓이면 나타납니다." />
      : null
  }
  const cap = limit ?? (fold && !expanded ? fold : undefined)
  const shown = cap ? visible.slice(0, cap) : visible
  const hidden = fold && !limit ? visible.length - shown.length : 0
  const list = shown.length === 0 ? (
        <EmptyState message={oldCount && !showOld ? `최근 ${STALE_DAYS}일 안에 갱신된 서사가 없습니다. 오래된 서사 ${oldCount}개를 켜서 볼 수 있습니다.` : "선택한 카테고리에 해당하는 내러티브가 없습니다."} />
      ) : (
        <div className="space-y-2.5">
          {shown.map((n) => (
            <Link
              key={n.topic}
              to={`/narrative?topic=${encodeURIComponent(n.topic)}`}
              className={cn("flex items-start gap-2 group", controls && isOld(n) && "opacity-60")}
            >
              <Sparkles className="h-4 w-4 text-hypothesis shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm leading-snug group-hover:underline">
                    {n.title ?? n.topic}
                  </span>
                  <Badge variant="outline" className="text-[10px]">{n.topic}</Badge>
                  {n.is_new ? (
                    <span className="text-[10px] text-up-ink">신규</span>
                  ) : n.share_delta_pp ? (
                    <span className="text-[10px] text-up-ink tabular-nums">+{n.share_delta_pp}%p</span>
                  ) : null}
                  {n.created_at && (
                    <span className="ml-auto shrink-0 text-[10px] text-muted-foreground tabular-nums">
                      {relUpdated(n.created_at)}
                    </span>
                  )}
                </div>
                {n.drift_summary ? (
                  <p className="text-xs line-clamp-2 mt-0.5">
                    <span className="text-hypothesis">바뀐 것 </span>
                    <span className="text-muted-foreground">{n.drift_summary}</span>
                  </p>
                ) : n.summary ? (
                  <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{n.summary}</p>
                ) : null}
              </div>
            </Link>
          ))}
        </div>
      )

  return (
    <div className="space-y-3">
      {controls && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <ToggleGroup type="multiple" size="sm" value={lenses} onValueChange={setLenses} aria-label="분야" className="flex-wrap">
            {LENS.map((l) => <ToggleGroupItem key={l.value} value={l.value} className="h-[30px] px-3 text-[13px]">{l.label}</ToggleGroupItem>)}
          </ToggleGroup>
          <div className="ml-auto flex items-center gap-1.5">
            <Switch id="narrative-old" checked={showOld} onCheckedChange={setShowOld} />
            <Label htmlFor="narrative-old" className="whitespace-nowrap text-xs font-normal text-muted-foreground">{STALE_DAYS}일 넘은 서사 <span className="inline-block min-w-[2ch] text-right tabular-nums">{oldCount}</span>개 보기</Label>
          </div>
          <ToggleGroup type="single" size="sm" value={sort} aria-label="정렬"
            onValueChange={(v) => v && setSort(v as SortKey)}>
            {SORT.map((s) => <ToggleGroupItem key={s.value} value={s.value} className="h-[30px] px-3 text-[13px]">{s.label}</ToggleGroupItem>)}
          </ToggleGroup>
        </div>
      )}

      {/* 랜딩 목록(fold)은 높이 고정 — 분야·정렬·더 보기를 바꿔도 카드가 그대로, 넘치면 안에서 스크롤 */}
      {fold && !limit ? <BoundedArea size="lg" fixed className="-mr-2" viewportClassName="pr-2">{list}</BoundedArea> : list}
      {/* 버튼 줄 자리는 늘 둔다 — 분야를 바꿔 더 볼 것이 없어져도 카드 높이 그대로 */}
      {fold && !limit && (hidden > 0 || (expanded && visible.length > fold) ? (
        <Button variant="ghost" size="sm" className="w-full text-ink-2" onClick={() => setParams(prev => { const next = new URLSearchParams(prev); if (hidden > 0) next.set("list", "all"); else next.delete("list"); return next }, { replace: true, preventScrollReset: true })}>
          {hidden > 0 ? `더 보기 · 전체 ${visible.length}편` : "접기"}
        </Button>
      ) : <div aria-hidden className="h-8" />)}
    </div>
  )
}
