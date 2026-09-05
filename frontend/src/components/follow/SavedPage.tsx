// 저장됨 페이지 — /follow/saved. 전체 목록 + kind 필터 + 인라인 메모·삭제 (D-078)
// + 문서 다중선택 → 교차 종합 (D-104, docs/specs/doc-synthesis.md)
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Bookmark, Layers } from "lucide-react"
import { toast } from "sonner"
import { PageContainer } from "@/components/shared/PageContainer"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { TableSkeleton } from "@/components/shared/Skeleton"
import SegmentTabs from "@/components/shared/SegmentTabs"
import SavedList from "@/components/follow/SavedList"
import RecentSyntheses from "@/components/follow/RecentSyntheses"
import { useSaved } from "@/hooks/useSaved"
import { useCreateSynthesis } from "@/hooks/useSynthesis"

const FILTERS = [
  { value: "all", label: "전체" },
  { value: "company", label: "기업" },
  { value: "doc", label: "문서" },
  { value: "narrative", label: "내러티브" },
  { value: "report", label: "리포트" },
  { value: "synthesis", label: "종합" },
]

const MAX_DOCS = 12

export default function SavedPage() {
  const { data: items = [], isLoading, isError, refetch } = useSaved()
  const [kind, setKind] = useState("all")
  const [picked, setPicked] = useState<number[]>([])
  const navigate = useNavigate()
  const create = useCreateSynthesis()

  const filtered = kind === "all" ? items : items.filter((it) => it.kind === kind)
  const hasDocs = items.some((it) => it.kind === "doc")

  const toggleDoc = (docId: number) =>
    setPicked((prev) => {
      if (prev.includes(docId)) return prev.filter((d) => d !== docId)
      if (prev.length >= MAX_DOCS) {
        toast(`한 번에 최대 ${MAX_DOCS}건까지 엮을 수 있어요`)
        return prev
      }
      return [...prev, docId]
    })

  const synthesize = () => {
    create.mutate(picked, {
      onSuccess: (data) => {
        setPicked([])
        toast.success("교차 종합 생성됨")
        navigate(`/synthesis/${data.id}`)
      },
      onError: () => toast.error("종합 생성 실패 — 다시 시도"),
    })
  }

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

          {/* 교차 종합 액션 바 — 저장된 문서가 있을 때만 (D-104) */}
          {hasDocs && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/30 px-3 py-2">
              <Layers className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">
                {picked.length === 0
                  ? "문서를 2건 이상 골라 엮으면, 함께 놓았을 때 무엇이 보이는지 종합해줍니다"
                  : picked.length === 1
                    ? "1건 선택 — 교차 종합은 2건 이상부터"
                    : `${picked.length}건 선택`}
              </span>
              <div className="ml-auto flex items-center gap-2">
                {picked.length > 0 && (
                  <Button variant="ghost" size="sm" onClick={() => setPicked([])} disabled={create.isPending}>
                    선택 해제
                  </Button>
                )}
                <Button size="sm" onClick={synthesize} disabled={picked.length < 2 || create.isPending}>
                  {create.isPending ? (
                    <><Spinner className="mr-1.5 h-3.5 w-3.5" /> 엮는 중…</>
                  ) : (
                    `${picked.length || ""}건 엮어 종합`.trim()
                  )}
                </Button>
              </div>
            </div>
          )}

          {filtered.length === 0 ? (
            <EmptyState message="이 유형의 저장 항목이 없습니다." />
          ) : (
            <Card>
              <CardContent className="py-1">
                <SavedList
                  items={filtered}
                  selectedDocIds={hasDocs ? picked : undefined}
                  onToggleDoc={hasDocs ? toggleDoc : undefined}
                />
              </CardContent>
            </Card>
          )}

          <RecentSyntheses />
        </div>
      )}
    </PageContainer>
  )
}
