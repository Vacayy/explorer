import { Link, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from '@/components/shared/PageContainer'
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { pinMine, useActions } from "@/hooks/useActions"
import { formatKrw } from "@/utils/format"
import { cn } from "@/lib/utils"
import RightsProTable from "@/components/actions/RightsProTable"
import type { ActionKind } from "@/types"

const TYPE_FILTERS = ["전체", "유상증자", "무상증자", "합병", "주식분할", "공개매수", "회사분할", "감자"] as const
const segItem = cn("h-auto min-w-0 rounded-none px-2.5 py-1 text-xs font-normal",
  "text-muted-foreground hover:bg-transparent hover:text-foreground",
  "data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:font-medium data-[state=on]:hover:bg-primary data-[state=on]:hover:text-primary-foreground")

/**
 * /actions — 기업활동 (시총 5,000억+ KOSPI/KOSDAQ)
 * DART 전 시장 공시에서 자동 분류. 30분 주기 갱신. 기본은 원공시만(정정은 ?kind=correction|all),
 * 내 묶음(보유·관심) 종목은 맨 위에 고정한다.
 */
export default function ActionsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const type = searchParams.get("type") ?? ""
  const view = searchParams.get("view") ?? "list"
  const kindParam = searchParams.get("kind")
  const kind: ActionKind = kindParam === "correction" || kindParam === "all" ? kindParam : "original"
  const { data, isLoading, isError, refetch } = useActions({ type: type || undefined, kind })
  const setParam = (k: string, v: string | null) => setSearchParams((p) => {
    const n = new URLSearchParams(p)
    if (v) n.set(k, v); else n.delete(k)
    return n
  })

  if (isLoading) return <ActionsSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />
  const items = pinMine(data.items)
  const mineCount = items.filter((a) => a.my_group).length

  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-xl font-bold">기업활동</h2>
          <p className="text-xs text-muted-foreground mt-0.5">시가총액 5,000억 이상 · 최근 30일 · DART 공시 자동 분류{mineCount > 0 && ` · 내 종목 ${mineCount}건 위로`}</p>
        </div>
        {data.as_of ? <FreshnessStamp asOf={data.as_of} />
          : <span className="text-caption text-muted-foreground">DART 스캔 성공 기록 없음</span>}
      </div>

      {/* 뷰 토글: 목록 | 유무증 Pro */}
      <div className="flex gap-1.5 items-center flex-wrap">
        <ToggleGroup
          type="single"
          value={view}
          onValueChange={(v) => v && setSearchParams(v === "list" ? {} : { view: v })}
          className="flex gap-0 rounded-md border overflow-hidden mr-2"
        >
          {[["list", "목록"], ["pro", "유무증 Pro"]].map(([v, label]) => (
            <ToggleGroupItem key={v} value={v} className={segItem}>{label}</ToggleGroupItem>
          ))}
        </ToggleGroup>
        {view === "list" && <>
          {/* 원공시 | 정정 | 전체 — 정정이 목록의 약 4할이라 기본은 원공시만 */}
          <ToggleGroup type="single" value={kind} aria-label="원공시·정정"
            onValueChange={(v) => v && setParam("kind", v === "original" ? null : v)}
            className="flex gap-0 rounded-md border overflow-hidden mr-2">
            <ToggleGroupItem value="original" className={segItem}>원공시 {data.counts?.original ?? ""}</ToggleGroupItem>
            <ToggleGroupItem value="correction" className={segItem}>정정 {data.counts?.correction ?? ""}</ToggleGroupItem>
            <ToggleGroupItem value="all" className={segItem}>전체</ToggleGroupItem>
          </ToggleGroup>
          {TYPE_FILTERS.map((t) => {
            const key = t === "전체" ? "" : t
            return (
              <Badge
                key={t}
                variant={type === key ? "default" : "outline"}
                className="cursor-pointer select-none text-xs"
                onClick={() => setParam("type", key || null)}
              >
                {t}
              </Badge>
            )
          })}
        </>}
      </div>

      {view === "pro" ? (
        <RightsProTable />
      ) : items.length === 0 ? (
        <EmptyState message={kind === "original" && data.counts?.correction ? `원공시는 없고 정정 공시 ${data.counts.correction}건이 있습니다.` : "해당 조건의 기업활동 공시가 없습니다."} />
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
            {items.map((a) => (
              <TableRow key={a.id} className={cn(a.my_group && "bg-accent/40")}>
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
                  {a.my_group && <Badge variant="outline" className="ml-1.5 h-4 px-1 text-[10px] border-up/40 text-up">{a.my_group}</Badge>}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums text-muted-foreground">
                  {a.market_cap ? formatKrw(a.market_cap) : "-"}
                </TableCell>
                <TableCell>
                  {a.is_correction && <Badge variant="outline" className="mr-1 h-4 px-1 text-[10px] text-muted-foreground">정정</Badge>}
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
    </PageContainer>
  )
}

function ActionsSkeleton() {
  return (
    <PageContainer gap="sm">
      <Skeleton className="h-6 w-32" />
      <Skeleton className="h-5 w-72" />
      {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </PageContainer>
  )
}
