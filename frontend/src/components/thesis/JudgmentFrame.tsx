import type { ReactNode } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { JUDGMENT_VIEWS, judgmentView } from "@/lib/judgment"

/**
 * Thesis › 내 판단 공통 틀(ia-redesign §4.10·§4.27, 시안 Questions·Question-Detail·Thesis-Audit·Report) —
 * 제목 '내 판단' + 보기 전환 `질문 · 논지 감사 · 리포트 · 지표 보드`. 보기는 주소가 정한다(/questions·/thesis·/report·/questions?view=proxies).
 * 옛 OutlookSubNav(프록시 보드 탭)를 대신한다.
 */
export function JudgmentFrame({ actions }: { actions?: ReactNode }) {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const value = judgmentView(pathname, search)
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-2xl font-bold">내 판단</h1>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs value={value} onValueChange={(v) => navigate(JUDGMENT_VIEWS.find((x) => x.key === v)!.to)}>
          <TabsList aria-label="내 판단 보기">
            {JUDGMENT_VIEWS.map((v) => <TabsTrigger key={v.key} value={v.key}>{v.label}</TabsTrigger>)}
          </TabsList>
        </Tabs>
        {actions}
      </div>
    </div>
  )
}
