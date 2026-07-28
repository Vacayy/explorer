// 저장됨 페이지 — /follow/saved. 전체 목록 + kind 필터 + 인라인 메모·삭제 (D-078)
import { useState } from "react"
import { Bookmark } from "lucide-react"
import { PageContainer } from "@/components/shared/PageContainer"
import { Card, CardContent } from "@/components/ui/card"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { TableSkeleton } from "@/components/shared/Skeleton"
import SegmentTabs from "@/components/shared/SegmentTabs"
import SavedList from "@/components/follow/SavedList"
import { useSaved } from "@/hooks/useSaved"

const FILTERS = [
  { value: "all", label: "전체" },
  { value: "company", label: "기업" },
  { value: "doc", label: "문서" },
  { value: "narrative", label: "내러티브" },
  { value: "report", label: "리포트" },
]

export default function SavedPage() {
  const { data: items = [], isLoading, isError, refetch } = useSaved()
  const [kind, setKind] = useState("all")
  const filtered = kind === "all" ? items : items.filter((it) => it.kind === kind)

  return (
    <PageContainer>
      <div className="flex items-center gap-2">
        <Bookmark className="h-5 w-5" />
        <h1 className="text-xl font-bold">저장됨</h1>
        {items.length > 0 && <span className="text-sm text-muted-foreground">{items.length}건</span>}
      </div>

      {isLoading ? (
        <Card><CardContent className="py-4"><TableSkeleton rows={5} /></CardContent></Card>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <EmptyState message="아직 저장한 항목이 없어요. 기업·문서·내러티브·리포트 페이지의 북마크 아이콘으로 저장하세요." />
      ) : (
        <div className="space-y-3">
          <SegmentTabs tabs={FILTERS} value={kind} onChange={setKind} />
          {filtered.length === 0 ? (
            <EmptyState message="이 유형의 저장 항목이 없습니다." />
          ) : (
            <Card><CardContent className="py-1"><SavedList items={filtered} /></CardContent></Card>
          )}
        </div>
      )}
    </PageContainer>
  )
}
