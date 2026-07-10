import { Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { formatKrw } from "@/utils/format"
import { cn } from "@/lib/utils"

interface CorporateAction {
  id: number
  rcp_no: string
  corp_name: string | null
  stock_code: string | null
  market: string | null
  action_type: string
  report_nm: string | null
  rcept_dt: string
  market_cap: number | null
  summary: string | null
  dart_url: string
}

const TYPE_FILTERS = ["전체", "유상증자", "무상증자", "합병", "주식분할", "공개매수", "회사분할", "감자"] as const

/**
 * /actions — 기업활동 (시총 5,000억+ KOSPI/KOSDAQ)
 * DART 전 시장 공시에서 자동 분류. 30분 주기 갱신.
 */
export default function ActionsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const type = searchParams.get("type") ?? ""
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["spine", "actions", type],
    queryFn: async () => {
      const { data } = await api.get("/api/spine/actions", { params: { type: type || undefined, days: 30 } })
      return data as { items: CorporateAction[]; total: number; as_of: string }
    },
    staleTime: 5 * 60_000,
  })

  if (isLoading) return <ActionsSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-xl font-bold">기업활동</h2>
          <p className="text-xs text-muted-foreground mt-0.5">시가총액 5,000억 이상 · 최근 30일 · DART 공시 자동 분류</p>
        </div>
        <FreshnessStamp asOf={data.as_of} />
      </div>

      <div className="flex gap-1.5 flex-wrap">
        {TYPE_FILTERS.map((t) => {
          const key = t === "전체" ? "" : t
          return (
            <Badge
              key={t}
              variant={type === key ? "default" : "outline"}
              className="cursor-pointer select-none text-xs"
              onClick={() => setSearchParams(key ? { type: key } : {})}
            >
              {t}
            </Badge>
          )
        })}
      </div>

      {data.items.length === 0 ? (
        <EmptyState message="해당 조건의 기업활동 공시가 없습니다." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[90px]">접수일</TableHead>
              <TableHead className="w-[90px]">유형</TableHead>
              <TableHead>기업</TableHead>
              <TableHead className="text-right w-[90px]">시총</TableHead>
              <TableHead>공시명</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="tabular-nums text-xs text-muted-foreground">
                  {a.rcept_dt.replace(/(\d{4})(\d{2})(\d{2})/, "$1-$2-$3")}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary" className={cn("text-[10px]",
                    a.action_type === "유상증자" && "bg-down/10 text-down",
                    a.action_type === "무상증자" && "bg-up/10 text-up",
                  )}>
                    {a.action_type}
                  </Badge>
                </TableCell>
                <TableCell>
                  {a.stock_code ? (
                    <Link to={`/analyze/${a.stock_code}/summary`} className="text-sm font-medium text-primary hover:underline">
                      {a.corp_name}
                    </Link>
                  ) : (
                    <span className="text-sm">{a.corp_name}</span>
                  )}
                  <span className="ml-1 text-[10px] text-muted-foreground">{a.market === "Y" ? "KOSPI" : "KOSDAQ"}</span>
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums text-muted-foreground">
                  {a.market_cap ? formatKrw(a.market_cap) : "-"}
                </TableCell>
                <TableCell>
                  <a href={a.dart_url} target="_blank" rel="noreferrer" className="text-xs hover:underline">
                    {a.report_nm}
                  </a>
                  {a.summary && (
                    <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2" title={a.summary}>
                      {a.summary}
                    </p>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

function ActionsSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-6 w-32" />
      <Skeleton className="h-5 w-72" />
      {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </div>
  )
}
