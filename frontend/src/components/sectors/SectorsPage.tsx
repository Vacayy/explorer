import { Navigate, useSearchParams } from "react-router-dom"
import { ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { PageContainer } from "@/components/shared/PageContainer"
import { PageLayout } from "@/components/shared/PageLayout"
import SectorBoard from "@/components/industry/SectorBoard"
import SectorMapPage from "@/components/map/SectorMapPage"

/**
 * /map — 산업 › 산업·섹터 (ia-redesign §4.7, docs/specs/explore-core.md §4).
 * 기본 = 섹터 상대강도 표 + 고른 섹터의 Peer 그룹(industry/SectorBoard, 4b단계).
 * 다른 보기는 산업 맵(view=map, RS 사분면) 하나. 유니버스·산업군 지도는 지웠다(D-319) —
 * 옛 ?view=universe|chains와 /follow/universe·/discover/industry는 /map으로 보낸다. 선택 섹터 = ?group=.
 */
const OTHER_VIEWS = [
  { key: "map", label: "산업 맵(RS 사분면)" },
] as const
type OtherView = (typeof OTHER_VIEWS)[number]["key"]

export default function SectorsPage() {
  const [params, setParams] = useSearchParams()
  const raw = params.get("view")
  const view: OtherView | null = OTHER_VIEWS.find((v) => v.key === raw)?.key ?? null
  // 보기를 바꾸면 그 보기의 상태(?group= 등)는 버린다 — 원천이 달라 이름이 맞지 않는다
  const setView = (v: OtherView | null) => setParams(v ? { view: v } : {}, { replace: true })

  if (raw && !view) return <Navigate to="/map" replace />

  const menu = <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs text-muted-foreground">{view ? OTHER_VIEWS.find(v => v.key === view)!.label : "다른 보기"}<ChevronDown className="size-3" /></Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      {view && <DropdownMenuItem onSelect={() => setView(null)}>섹터 상대강도</DropdownMenuItem>}
      {OTHER_VIEWS.filter(v => v.key !== view).map(v => <DropdownMenuItem key={v.key} onSelect={() => setView(v.key)}>{v.label}</DropdownMenuItem>)}
    </DropdownMenuContent>
  </DropdownMenu>

  if (!view) return <PageLayout mode="document"><SectorBoard viewMenu={menu} /></PageLayout>
  return (
    <PageContainer gap="sm">
      <div className="flex justify-end">{menu}</div>
      <SectorMapPage />
    </PageContainer>
  )
}
