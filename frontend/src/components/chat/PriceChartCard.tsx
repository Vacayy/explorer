import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useQueries } from "@tanstack/react-query"
import api from "@/api/client"
import MultiLineChart from "@/components/charts/MultiLineChart"
import { Skeleton } from "@/components/ui/skeleton"
import type { PriceSnapshot } from "@/types"
import { formatNumber } from "@/utils/format"
import type { Citation } from "./citations"

interface Target {
  code: string
  name: string
}

/** `prices` 인용(href=/analyze/:code/summary, title="삼성전자 일별 시세 최근 10거래일") → 종목·거래일 수 */
export function priceTargets(citations: Citation[] | null): { targets: Target[]; days: number } | null {
  if (!citations) return null
  const seen = new Set<string>()
  const targets: Target[] = []
  let days = 0
  for (const c of citations) {
    if (c.kind !== "prices") continue
    const code = c.href?.match(/^\/analyze\/([^/]+)\//)?.[1]
    if (!code || seen.has(code)) continue
    seen.add(code)
    targets.push({ code, name: c.title.split(" 일별 시세")[0] || code })
    days = Math.max(days, Number(c.title.match(/최근 (\d+)거래일/)?.[1] ?? 0))
  }
  if (targets.length === 0) return null
  return { targets: targets.slice(0, 4), days: days || 10 }
}

/** 캔버스 차트는 CSS 변수를 못 읽는다 — 마운트 시 계산값으로 해석(라이트·다크 대응) */
function useChartPalette(n: number) {
  const [colors, setColors] = useState<string[]>([])
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement)
    setColors(Array.from({ length: n }, (_, i) => cs.getPropertyValue(`--chart-${(i % 5) + 1}`).trim() || "#888"))
  }, [n])
  return colors
}

/**
 * 시세 차트 카드 — 답변이 `prices` 근거를 인용했을 때 본문 아래에 자동으로 붙는다 (docs/specs/chat-page.md §4).
 * 종목 1개=종가 라인, 2개 이상=첫 거래일 대비 등락률(%) 비교선. 데이터는 답변이 읽은 것과 같은
 * stock_prices 스냅샷(16:10)이라 표·본문 숫자와 어긋나지 않는다. 실패하면 조용히 숨김(보조 UI).
 */
export function PriceChartCard({ targets, days }: { targets: Target[]; days: number }) {
  const queries = useQueries({
    queries: targets.map((t) => ({
      queryKey: ["price-snapshot", t.code, days],
      queryFn: async () => (await api.get<PriceSnapshot>(`/api/stock-prices/${t.code}/snapshot`, { params: { days } })).data,
      staleTime: 5 * 60_000,
    })),
  })
  const colors = useChartPalette(targets.length)
  const loading = queries.some((q) => q.isLoading)
  const snaps = queries.map((q) => q.data).filter((d): d is PriceSnapshot => !!d && d.items.length >= 2)
  const compare = targets.length > 1

  const { data, lines } = useMemo(() => {
    const byDate = new Map<string, Record<string, unknown>>()
    const lines = snaps.map((s, i) => {
      const first = s.items.find((it) => it.close != null)?.close ?? null
      for (const it of s.items) {
        if (it.close == null) continue
        const row = byDate.get(it.trade_date) ?? { time: it.trade_date }
        row[s.stock_code] = compare && first ? (it.close / first - 1) * 100 : it.close
        byDate.set(it.trade_date, row)
      }
      return { key: s.stock_code, label: s.name, color: colors[i] ?? "#888" }
    })
    return { data: [...byDate.values()].sort((a, b) => String(a.time).localeCompare(String(b.time))), lines }
  }, [snaps, colors, compare])

  if (!loading && snaps.length === 0) return null

  const title = targets.map((t) => t.name).join(" vs ")
  const range = data.length ? `${String(data[0].time).slice(5)} ~ ${String(data[data.length - 1].time).slice(5)}` : `최근 ${days}거래일`
  return (
    <figure className="rounded-xl bg-card px-4 pt-3 pb-2 ring-1 ring-border">
      <figcaption className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
        <span className="font-medium">{title}</span>
        <span className="text-muted-foreground">{compare ? "등락률 비교" : "종가"} · {range}</span>
        <span className="ml-auto text-[11px] text-muted-foreground">16:10 스냅샷 기준</span>
        {targets.map((t) => (
          <Link key={t.code} to={`/analyze/${t.code}/summary`} className="text-[11px] text-muted-foreground hover:text-primary">
            {t.name} 도시에 →
          </Link>
        ))}
      </figcaption>
      <div className="mt-1">
        {loading || colors.length === 0 ? (
          <Skeleton className="h-[200px] w-full rounded-lg" />
        ) : (
          <MultiLineChart data={data} lines={lines} height={200}
            formatValue={compare ? (v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` : (v) => formatNumber(v)} />
        )}
      </div>
    </figure>
  )
}
