import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { usListQuery } from "@/api/spine"
import { PageContainer } from "@/components/shared/PageContainer"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import type { UsListItem } from "@/types"

// group_label(백엔드 원시값) → 표시 라벨
const GROUP_LABEL: Record<string, string> = {
  M7: "M7", hyperscaler: "하이퍼스케일러", "ai-datacenter": "AI 데이터센터", "dc-infra": "DC 인프라",
  energy: "에너지", power: "전력", cpo: "CPO", semicap: "반도체 장비", memory: "메모리",
  networking: "네트워킹", server: "서버", software: "소프트웨어", nasdaq: "나스닥", space: "우주", web3: "Web3",
  기타: "기타",
}
const VALUE_CLS: Record<string, string> = { 강: "text-up border-up/40", 중: "text-hypothesis border-hypothesis/40", 약: "text-down border-down/40" }
const TREND_CLS: Record<string, string> = { 초입: "text-up border-up/40", 진행: "text-up border-up/40", 성숙: "text-down border-down/40", 훼손: "text-down border-down/40", 불명확: "text-muted-foreground border-border" }

/**
 * 미국 종목 디렉토리 (docs/specs/us-dossier.md) — transcript_follow(=US 유니버스)를 그룹별로 브라우징.
 * 각 카드 → /us/:ticker 도시에. 렌즈 판독이 있으면 stance 배지로 미리보기.
 */
export default function UsIndexPage() {
  const q = useQuery(usListQuery())

  if (q.isLoading)
    return (
      <PageContainer>
        <Skeleton className="h-64 w-full rounded-xl" />
      </PageContainer>
    )
  if (q.isError || !q.data)
    return (
      <PageContainer>
        <ErrorState onRetry={() => q.refetch()} />
      </PageContainer>
    )

  const groups = q.data.groups
  const total = groups.reduce((n, g) => n + g.items.length, 0)

  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">미국 종목 {total}</h1>
        <span className="text-xs text-muted-foreground">
          컨콜 팔로우 = 커버리지. 카드 → 도시에(시세·밸류·투자 렌즈)
        </span>
      </div>

      {total === 0 ? (
        <EmptyState message="팔로우한 미국 기업이 없습니다 — 컨콜 탭에서 기본 세트를 시드하세요." />
      ) : (
        groups.map((g) => (
          <div key={g.label} className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">
              {GROUP_LABEL[g.label] ?? g.label} · {g.items.length}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {g.items.map((it) => (
                <UsCard key={it.ticker} item={it} />
              ))}
            </div>
          </div>
        ))
      )}
    </PageContainer>
  )
}

function UsCard({ item }: { item: UsListItem }) {
  return (
    <Link
      to={`/us/${item.ticker}`}
      className="group flex flex-col gap-1.5 rounded-xl border p-3 hover:border-foreground/30 hover:bg-accent/40 transition-colors"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold tabular-nums">{item.ticker}</span>
        {item.price != null && <span className="text-xs text-muted-foreground tabular-nums">${item.price.toFixed(2)}</span>}
      </div>
      <span className="truncate text-xs text-muted-foreground">{item.name}</span>
      <div className="flex flex-wrap items-center gap-1 pt-0.5 min-h-[20px]">
        {item.value_stance && (
          <Badge variant="outline" className={`text-[10px] font-normal ${VALUE_CLS[item.value_stance] ?? ""}`}>
            가치 {item.value_stance}
          </Badge>
        )}
        {item.trend_stance && (
          <Badge variant="outline" className={`text-[10px] font-normal ${TREND_CLS[item.trend_stance] ?? ""}`}>
            추세 {item.trend_stance}
          </Badge>
        )}
        {item.quadrant_cell && (
          <span className="text-[10px] text-muted-foreground ml-auto">{item.quadrant_cell}</span>
        )}
        {!item.value_stance && !item.trend_stance && (
          <span className="text-[10px] text-muted-foreground">렌즈 미생성 — 열어서 생성</span>
        )}
      </div>
    </Link>
  )
}
