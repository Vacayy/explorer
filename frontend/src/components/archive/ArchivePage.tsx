import { Link } from "react-router-dom"
import { Archive, GitCompare, NotebookPen, CalendarDays, Map, Filter, Bitcoin } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PageContainer } from "@/components/shared/PageContainer"

/**
 * /archive — 보관함 (휴지통). 잘 안 쓰는 화면을 메인 네비에서 뺐지만 삭제하지 않는다.
 * 여기와 옴니바(⌘K)에서 여전히 접근 가능. 다시 자주 쓰게 되면 메인으로 승격.
 */

const ARCHIVED = [
  { to: "/analyze/compare", icon: GitCompare, title: "VS 비교", desc: "종목 여러 개 지표 나란히 비교" },
  { to: "/research/memos", icon: NotebookPen, title: "투자메모", desc: "종목별 IR 메모 (vault 노트로 이관 예정)" },
  { to: "/research/catalysts", icon: CalendarDays, title: "카탈리스트 캘린더", desc: "이벤트 수동 관리 (홈 캘린더 스트립이 표시 담당)" },
  { to: "/discover/industry", icon: Map, title: "산업군 지도", desc: "수동 밸류체인 맵" },
  { to: "/discover/screener", icon: Filter, title: "스크리너", desc: "재무 지표 필터" },
  { to: "/discover/alt-data", icon: Bitcoin, title: "대안데이터", desc: "온체인·폴리마켓" },
] as const

export default function ArchivePage() {
  return (
    <PageContainer width="reading" gap="sm">
      <div>
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Archive className="h-5 w-5 text-muted-foreground" /> 보관함
        </h2>
        <p className="text-xs text-muted-foreground mt-1">
          자주 쓰지 않아 메인 메뉴에서 뺀 화면들입니다. 삭제된 게 아니며, 여기 또는 ⌘K로 언제든 접근할 수 있습니다.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {ARCHIVED.map((a) => (
          <Link key={a.to} to={a.to}>
            <Card className="hover:bg-muted/40 transition-colors h-full">
              <CardContent className="py-3 flex items-start gap-3">
                <a.icon className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
                <div>
                  <div className="text-sm font-medium">{a.title}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">{a.desc}</div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </PageContainer>
  )
}
