import { useNavigate, useSearchParams } from "react-router-dom"
import { ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { PageContainer } from "@/components/shared/PageContainer"
import { PageLayout } from "@/components/shared/PageLayout"
import SectorBoard from "@/components/industry/SectorBoard"
import SectorMapPage from "@/components/map/SectorMapPage"
import UniversePage from "@/components/follow/UniversePage"
import IndustryPage from "@/components/industry/IndustryPage"

/**
 * /map — 산업 › 산업·섹터 (ia-redesign §4.7, docs/specs/explore-core.md §4).
 * 기본 = 섹터 상대강도 표 + 고른 섹터의 Peer 그룹(industry/SectorBoard, 4b단계).
 * 옛 세 보기는 ?view=로 그대로 연다: 산업 맵(view=map, RS 사분면) · 유니버스(view=universe) · 산업군 지도(view=chains).
 * 옛 /follow/universe, /discover/industry 리다이렉트가 이 보기들을 가리킨다. 선택 섹터 = ?group=(두 화면 공통).
 */
const OTHER_VIEWS = [
  { key: "map", label: "산업 맵(RS 사분면)" },
  { key: "universe", label: "유니버스" },
  { key: "chains", label: "산업군 지도" },
] as const
type OtherView = (typeof OTHER_VIEWS)[number]["key"]

export default function SectorsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const view: OtherView | null = OTHER_VIEWS.find((v) => v.key === params.get("view"))?.key ?? null
  // 보기를 바꾸면 그 보기의 상태(?group= 등)는 버린다 — 원천이 달라 이름이 맞지 않는다
  const setView = (v: OtherView | null) => setParams(v ? { view: v } : {}, { replace: true })

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
      {view === "map" && <SectorMapPage />}
      {view === "universe" && <UniversePage />}
      {view === "chains" && (
        <IndustryPage onSelectCompany={(c) => { if (c.stock_code) navigate(`/analyze/${c.stock_code}/summary`) }} />
      )}
    </PageContainer>
  )
}
