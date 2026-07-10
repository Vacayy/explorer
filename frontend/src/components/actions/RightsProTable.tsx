import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import api from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { cn } from "@/lib/utils"

interface RightsRow {
  rcp_no: string
  stock_code: string | null
  corp_name: string | null
  action_type: string | null
  method: string | null
  price_1st: number | null
  price_2nd: number | null
  price_final: number | null
  latest_close: number | null
  diff_w: number | null
  diff_pct: number | null
  old_shares: number | null
  new_shares: number | null
  ratio_pct: number | null
  date_disclosure: string | null
  date_price_1st: string | null
  date_ex_rights: string | null
  date_record: string | null
  date_rights_listing_start: string | null
  date_price_fix: string | null
  date_sub_start: string | null
  date_public_start: string | null
  date_payment: string | null
  date_rights_listing_end: string | null
  date_new_listing: string | null
  underwriter: string | null
  major_holder: string | null
  dart_url: string
}

const DATE_COLS: { key: keyof RightsRow; label: string }[] = [
  { key: "date_disclosure", label: "공시일" },
  { key: "date_price_1st", label: "1차발행가" },
  { key: "date_ex_rights", label: "권리락*" },
  { key: "date_record", label: "기준일" },
  { key: "date_rights_listing_start", label: "증서 상장" },
  { key: "date_price_fix", label: "발행가확정" },
  { key: "date_sub_start", label: "구주주청약" },
  { key: "date_public_start", label: "일반공모" },
  { key: "date_payment", label: "납입일" },
  { key: "date_rights_listing_end", label: "권리매도" },
  { key: "date_new_listing", label: "상장일" },
]

const num = (v: number | null | undefined) => (v == null ? "-" : v.toLocaleString())
const shortDate = (v: string | null) => (v ? v.slice(2).replace(/-/g, "/") : "-")

/**
 * 유무증 Pro 테이블 — 리서치 엑셀(유무증 탭) 재현.
 * 셀 하이라이트: 각 행의 '다음 도래 일정'을 강조 (노랑), 미래 일정은 옅게.
 * WR·유증매수가는 신주인수권증서 시세 필요 — 데이터 확보 전까지 '-' (v2).
 */
export default function RightsProTable() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["spine", "actions", "rights"],
    queryFn: async () => (await api.get("/api/spine/actions/rights")).data as { items: RightsRow[]; as_of: string },
    staleTime: 5 * 60_000,
  })

  if (isLoading) return <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />
  if (data.items.length === 0) return <EmptyState message="추출된 유·무상증자 상세가 아직 없습니다." />

  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="overflow-x-auto border rounded-lg">
      <table className="text-xs tabular-nums whitespace-nowrap w-max min-w-full">
        <thead>
          <tr className="bg-muted/60 text-muted-foreground">
            <th className="sticky left-0 bg-muted px-2 py-1.5 text-left z-10">종목명</th>
            {["WR", "1차발행가", "2차발행가", "최종발행가", "유증매수가", "차액(₩)", "차액(%)", "구주수", "신주수", "증자비율"].map((h) => (
              <th key={h} className="px-2 py-1.5 text-right font-medium">{h}</th>
            ))}
            {DATE_COLS.map((c) => (
              <th key={c.key} className="px-2 py-1.5 text-center font-medium">{c.label}</th>
            ))}
            <th className="px-2 py-1.5 text-left font-medium">주관사</th>
            <th className="px-2 py-1.5 text-left font-medium">최대주주</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {data.items.map((r) => {
            const futureDates = DATE_COLS.map((c) => r[c.key] as string | null)
              .filter((d): d is string => !!d && d >= today)
            const nextDate = futureDates.length ? futureDates.reduce((a, b) => (a < b ? a : b)) : null
            return (
              <tr key={r.rcp_no} className="hover:bg-muted/30">
                <td className="sticky left-0 bg-background px-2 py-1.5 z-10">
                  <div className="flex items-center gap-1">
                    {r.stock_code ? (
                      <Link to={`/analyze/${r.stock_code}/summary`} className="font-medium text-primary hover:underline">
                        {r.corp_name}
                      </Link>
                    ) : <span className="font-medium">{r.corp_name}</span>}
                    <Badge variant="secondary" className="text-[9px] px-1">
                      {r.action_type === "무상증자" ? "무증" : r.method ?? "유증"}
                    </Badge>
                    <a href={r.dart_url} target="_blank" rel="noreferrer" className="text-muted-foreground hover:text-foreground text-[10px]" title="DART 원문">↗</a>
                  </div>
                </td>
                <td className="px-2 py-1.5 text-right text-muted-foreground">-</td>
                <td className="px-2 py-1.5 text-right">{num(r.price_1st)}</td>
                <td className="px-2 py-1.5 text-right">{num(r.price_2nd)}</td>
                <td className="px-2 py-1.5 text-right font-medium">{num(r.price_final)}</td>
                <td className="px-2 py-1.5 text-right text-muted-foreground">-</td>
                <td className={cn("px-2 py-1.5 text-right", (r.diff_w ?? 0) > 0 ? "text-up" : (r.diff_w ?? 0) < 0 ? "text-down" : "")}>
                  {num(r.diff_w)}
                </td>
                <td className={cn("px-2 py-1.5 text-right", (r.diff_pct ?? 0) > 0 ? "text-up" : (r.diff_pct ?? 0) < 0 ? "text-down" : "")}>
                  {r.diff_pct == null ? "-" : `${r.diff_pct}%`}
                </td>
                <td className="px-2 py-1.5 text-right">{num(r.old_shares)}</td>
                <td className="px-2 py-1.5 text-right">{num(r.new_shares)}</td>
                <td className="px-2 py-1.5 text-right">{r.ratio_pct == null ? "-" : `${r.ratio_pct}%`}</td>
                {DATE_COLS.map((c) => {
                  const v = r[c.key] as string | null
                  const isNext = v && v === nextDate
                  const isFuture = v && v >= today
                  return (
                    <td key={c.key} className={cn("px-2 py-1.5 text-center",
                      isNext && "bg-hypothesis/20 font-semibold rounded",
                      !isNext && isFuture && "text-foreground",
                      !isFuture && "text-muted-foreground")}>
                      {shortDate(v)}
                    </td>
                  )
                })}
                <td className="px-2 py-1.5 max-w-[140px] truncate" title={r.underwriter ?? undefined}>{r.underwriter ?? "-"}</td>
                <td className="px-2 py-1.5 max-w-[120px] truncate" title={r.major_holder ?? undefined}>{r.major_holder ?? "-"}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="text-[10px] text-muted-foreground px-2 py-1.5 border-t">
        * 권리락 = 기준일−1거래일 파생(공휴일 근사) · 차액 = 최근 종가 − 유효발행가(확정&gt;2차&gt;1차) ·
        WR·유증매수가는 신주인수권증서 시세 연동 예정 · <span className="bg-hypothesis/20 px-1 rounded">노랑</span> = 다음 도래 일정
      </p>
    </div>
  )
}
