// 피드 › 저장됨 — /feed/saved (옛 /follow/saved). 유형 필터(건수) + 메모·저장 해제 (D-078, ia-redesign §4.26)
import { useSearchParams } from "react-router-dom"
import { PageLayout } from "@/components/shared/PageLayout"
import { ErrorState } from "@/components/shared/ErrorState"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { InfoTip } from "@/components/regimes/Section"
import { Skeleton } from "@/components/ui/skeleton"
import SavedList from "@/components/follow/SavedList"
import { useSaved } from "@/hooks/useSaved"
import { savedCounts, SAVED_FILTERS, type SavedFilter } from "@/lib/saved"
import { formatNumber } from "@/utils/format"

export default function SavedPage() {
  const query = useSaved()
  const items = query.data ?? []
  const [params, setParams] = useSearchParams()
  const kind = (SAVED_FILTERS.some(f => f.value === params.get("kind")) ? params.get("kind") : "all") as SavedFilter
  const counts = savedCounts(items)
  const filtered = kind === "all" ? items : items.filter((it) => it.kind === kind)

  return (
    <PageLayout mode="document">
      <div className="max-w-[980px] space-y-4">
        <header className="flex items-baseline gap-2">
          <h1 className="text-page font-semibold">저장됨</h1>
          {query.data && <span className="text-caption text-muted-foreground tabular-nums">{formatNumber(items.length)}건</span>}
          <InfoTip label="저장하는 방법" className="self-center">기업·문서·내러티브·리포트 화면의 북마크 아이콘으로 저장합니다. 상단 바 인박스에서도 볼 수 있어요.</InfoTip>
        </header>

        {query.isLoading && <div role="status" aria-label="저장 목록 불러오는 중" className="space-y-3 border p-4">
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>}
        {query.isError && <ErrorState message="저장 목록을 불러오지 못했습니다" onRetry={() => void query.refetch()} />}
        {query.data && items.length === 0 && <div className="border px-6 py-12 text-center">
          <p className="text-sm">아직 저장한 항목이 없어요</p>
          <p className="mt-1 text-caption text-muted-foreground">기업·문서·내러티브·리포트 화면의 북마크 아이콘으로 저장하세요.</p>
        </div>}
        {query.data && items.length > 0 && <>
          <SegmentTabs
            tabs={SAVED_FILTERS.map(f => ({ value: f.value, label: `${f.label} ${formatNumber(counts[f.value])}` }))}
            value={kind}
            onChange={(v) => setParams(v === "all" ? {} : { kind: v }, { replace: true })}
            className="max-w-full overflow-x-auto"
          />
          {filtered.length === 0
            ? <p className="border px-6 py-10 text-center text-sm text-muted-foreground">이 유형의 저장 항목이 없습니다.</p>
            : <div className="border bg-card"><SavedList items={filtered} /></div>}
        </>}
      </div>
    </PageLayout>
  )
}
