import { useMemo, useState } from "react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Sparkles } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { EmptyState } from "@/components/shared/ErrorState"
import { formatRelativeTime } from "@/utils/format"
import { cn } from "@/lib/utils"

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
  empty = "hide",
  controls = false,
}: {
  limit?: number
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

  const filtered = useMemo(() => {
    if (!controls) return items   // 티저 등 — 백엔드 순서(급증 우선) 유지
    const picked = new Set(lenses)
    const matched = picked.size
      ? items.filter((n) => (n.category ?? "").split(",").some((c) => picked.has(c)))
      : items
    return [...matched].sort(sortFns[sort])
  }, [items, lenses, sort, controls])

  if (items.length === 0) {
    return empty === "state"
      ? <EmptyState message="아직 생성된 내러티브가 없습니다 — 주목 주제가 쌓이면 나타납니다." />
      : null
  }
  const shown = limit ? filtered.slice(0, limit) : filtered

  return (
    <div className="space-y-3">
      {controls && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <ToggleGroup
            type="multiple"
            value={lenses}
            onValueChange={setLenses}
            className="flex flex-wrap gap-1.5 w-auto"
          >
            {LENS.map((l) => (
              <ToggleGroupItem
                key={l.value}
                value={l.value}
                className={cn(
                  "h-7 px-3 text-xs rounded-lg text-muted-foreground",
                  "data-[state=on]:border data-[state=on]:border-primary data-[state=on]:text-primary data-[state=on]:bg-accent data-[state=on]:hover:bg-accent",
                )}
              >
                {l.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
            <SelectTrigger className="h-7 w-28 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT.map((s) => (
                <SelectItem key={s.value} value={s.value} className="text-xs">
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {shown.length === 0 ? (
        <EmptyState message="선택한 카테고리에 해당하는 내러티브가 없습니다." />
      ) : (
        <div className="space-y-2.5">
          {shown.map((n) => (
            <Link
              key={n.topic}
              to={`/narrative?topic=${encodeURIComponent(n.topic)}`}
              className="flex items-start gap-2 group"
            >
              <Sparkles className="h-4 w-4 text-hypothesis shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm leading-snug group-hover:underline">
                    {n.title ?? n.topic}
                  </span>
                  <Badge variant="outline" className="text-[10px]">{n.topic}</Badge>
                  {n.is_new ? (
                    <span className="text-[10px] text-up">신규</span>
                  ) : n.share_delta_pp ? (
                    <span className="text-[10px] text-up tabular-nums">+{n.share_delta_pp}%p</span>
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
      )}
    </div>
  )
}
