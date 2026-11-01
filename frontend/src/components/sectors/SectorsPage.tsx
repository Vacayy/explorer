import { useNavigate, useSearchParams } from "react-router-dom"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PageContainer } from "@/components/shared/PageContainer"
import SectorMapPage from "@/components/map/SectorMapPage"
import UniversePage from "@/components/follow/UniversePage"
import IndustryPage from "@/components/industry/IndustryPage"

/**
 * /map — 탐색 › 산업·섹터 (docs/specs/explore-core.md §4).
 * 세 화면을 한 탭에서 본다: 산업 맵(sector_map 18 대분류 RS 사분면) · 유니버스(industry_groups 큐레이션·섹터 서사)
 * · 산업군 지도(industry_groups 밸류체인 표). 섹터 원천 두 개는 합치지 않고 함께 보이기만 한다.
 * 상태 = ?view= (map 기본). 옛 /follow/universe, /discover/industry는 이 탭으로 리다이렉트.
 */
const SECTOR_VIEWS = [
  { key: "map", label: "산업 맵" },
  { key: "universe", label: "유니버스" },
  { key: "chains", label: "산업군 지도" },
] as const
type SectorView = (typeof SECTOR_VIEWS)[number]["key"]

export default function SectorsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const view: SectorView = SECTOR_VIEWS.find((v) => v.key === params.get("view"))?.key ?? "map"

  // 뷰를 바꾸면 그 뷰의 상태(?group= 등)는 버린다 — 원천이 달라 이름이 맞지 않는다
  const setView = (v: string) => setParams(v === "map" ? {} : { view: v }, { replace: true })

  return (
    <PageContainer gap="sm">
      <Tabs value={view} onValueChange={setView}>
        <TabsList>
          {SECTOR_VIEWS.map((v) => <TabsTrigger key={v.key} value={v.key}>{v.label}</TabsTrigger>)}
        </TabsList>
      </Tabs>
      {view === "map" && <SectorMapPage />}
      {view === "universe" && <UniversePage />}
      {view === "chains" && (
        <IndustryPage onSelectCompany={(c) => { if (c.stock_code) navigate(`/analyze/${c.stock_code}/summary`) }} />
      )}
    </PageContainer>
  )
}
