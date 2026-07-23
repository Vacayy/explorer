import { Link } from "react-router-dom"
import { Archive, GitCompare, NotebookPen, CalendarDays, Map, Filter, Bitcoin } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { PageContainer } from "@/components/shared/PageContainer"

/**
 * /archive — 보관함 (휴지통). 잘 안 쓰는 화면을 메인 네비에서 뺐지만 삭제하지 않는다.
 * 여기와 옴니바(⌘K)에서 여전히 접근 가능. 다시 자주 쓰게 되면 메인으로 승격.
 */

const ARCHIVED = [
  { to: "/analyze/compare", icon: GitCompare, title: "VS 비교", desc: "종목 여러 개 지표 나란히 비교" },
  { to: "/research/memos", icon: NotebookPen, title: "투자메모", desc: "종목별 IR 메모 (vault 노트로 이관 예정)" },
  { to: "/research/catalysts", icon: CalendarDays, title: "카탈리스트 캘린더", desc: "이벤트 수동 관리 · 일정 표시는 기업활동(팔로우)이 담당" },
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

      {/* 신호 성적표 — 탐색 해체로 이관 (D-057). 자주 안 보는 자기검증 도구 */}
      <BacktestSection />
    </PageContainer>
  )
}

/* ---------- 신호 성적표 — 언급 급증 후 5거래일 수익률 (신호 유효성 자기 검증) ---------- */

function BacktestSection() {
  const { data } = useQuery({
    queryKey: ["spine", "backtest"],
    queryFn: async () => (await api.get("/api/spine/signals/backtest")).data as {
      items: { date: string; name: string; stock_code: string | null; ret_5d: number | null }[]
      avg_ret: number | null
      hit_rate: number | null
      n: number
    },
    staleTime: 30 * 60_000,
  })
  if (!data || data.n === 0) return null
  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-baseline gap-3">
        <CardTitle className="text-sm">신호 성적표 — 언급 급증 후 5거래일</CardTitle>
        <span className="text-xs tabular-nums">
          평균 <b className={data.avg_ret! > 0 ? "text-up" : "text-down"}>{data.avg_ret}%</b>
          <span className="text-muted-foreground"> · 적중 {data.hit_rate}% · {data.n}건</span>
        </span>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
          {data.items.filter((i) => i.ret_5d != null).slice(0, 12).map((i, idx) => (
            <span key={idx}>
              <span className="text-muted-foreground">{i.date.slice(5)}</span>{" "}
              {i.name}{" "}
              <b className={i.ret_5d! > 0 ? "text-up" : "text-down"}>
                {i.ret_5d! > 0 ? "+" : ""}{i.ret_5d}%
              </b>
            </span>
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground mt-2">
          과거 신호의 사후 수익률 — 신호의 유효성 자체를 검증하기 위한 것 (투자 추천 아님)
        </p>
      </CardContent>
    </Card>
  )
}
