import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { PageContainer } from "@/components/shared/PageContainer"
import { formatKrw } from "@/utils/format"
import { cn } from "@/lib/utils"

/**
 * /map — 산업/섹터 맵 (RS 4사분면).
 * x=장기 RS(11개월 수익률 백분위, 구조적 강도) · y=단기 RS(1개월, 현재 수급)
 * 크기=시총 · 색=5일 흐름 · hover=1~3주 전 궤적. 사분면: 주도/부상/소외/과열·경계.
 * 그룹 축: KSIC 165 → 투자 언어 대분류 18 (LLM 시드, sector_map).
 */

interface TrailPoint { weeks_ago: number; rs_long: number | null; rs_short: number | null }
interface SectorGroup {
  name: string; market_cap: number; stocks: number
  rs_long: number | null; rs_short: number | null; chg_5d: number; trail: TrailPoint[]
}
interface MemberRow {
  stock_code: string; corp_name: string; market_cap: number | null
  rs_long: number | null; rs_short: number | null; ret_1m: number | null; ret_12m: number | null
}

const flowColor = (chg: number) => {
  const a = Math.min(0.9, 0.3 + Math.abs(chg) / 12)
  return chg >= 0 ? `rgba(220, 38, 38, ${a})` : `rgba(37, 99, 235, ${a})`
}

export default function SectorMapPage() {
  const navigate = useNavigate()
  const [hovered, setHovered] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const { data, isLoading, isError, refetch } = useQuery(
    apiQuery<{ as_of: string | null; groups: SectorGroup[] }>({
      key: ["spine", "sector-map"], url: "/api/spine/sector-map", staleTime: STALE.medium,
    }),
  )

  const totalMcap = useMemo(
    () => (data?.groups ?? []).reduce((s, g) => s + g.market_cap, 0), [data])
  const hoveredGroup = data?.groups.find((g) => g.name === hovered)
  const trailData = useMemo(() => {
    if (!hoveredGroup) return []
    const pts = [...hoveredGroup.trail]
      .sort((a, b) => b.weeks_ago - a.weeks_ago)
      .filter((t) => t.rs_long != null && t.rs_short != null)
      .map((t) => ({ rs_long: t.rs_long!, rs_short: t.rs_short!, label: `${t.weeks_ago}주 전` }))
    return [...pts, { rs_long: hoveredGroup.rs_long!, rs_short: hoveredGroup.rs_short!, label: "현재" }]
  }, [hoveredGroup])

  if (isLoading) return (
    <PageContainer gap="sm"><Skeleton className="h-7 w-40" /><Skeleton className="h-[480px] w-full rounded-xl" /></PageContainer>
  )
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />
  if (data.groups.length === 0) return <EmptyState message="주가·섹터 데이터가 쌓이면 나타납니다." />

  return (
    <PageContainer gap="sm">
      <div className="flex items-baseline gap-2 flex-wrap">
        <h2 className="text-xl font-bold">산업/섹터 맵</h2>
        <span className="text-xs text-muted-foreground">
          크기=시총 · 색=5일 흐름 · 점에 올리면 3주 궤적 · {data.as_of} 기준
        </span>
      </div>

      <Card>
        <CardContent className="pt-4">
          <div className="relative">
            {/* 사분면 라벨 */}
            <span className="absolute right-8 top-6 text-lg font-bold text-muted-foreground/25 select-none">주도</span>
            <span className="absolute left-14 top-6 text-lg font-bold text-muted-foreground/25 select-none">부상</span>
            <span className="absolute left-14 bottom-14 text-lg font-bold text-muted-foreground/25 select-none">소외</span>
            <span className="absolute right-8 bottom-14 text-lg font-bold text-muted-foreground/25 select-none">과열·경계</span>
            <ResponsiveContainer width="100%" height={480}>
              <ScatterChart margin={{ top: 16, right: 24, bottom: 8, left: -18 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
                <XAxis type="number" dataKey="rs_long" domain={[-4, 104]} ticks={[0, 25, 50, 75, 100]}
                  tick={{ fontSize: 10 }} label={{ value: "장기 RS (구조적 강도) →", position: "insideBottom", offset: -2, fontSize: 11 }} />
                <YAxis type="number" dataKey="rs_short" domain={[-4, 104]} ticks={[0, 25, 50, 75, 100]}
                  tick={{ fontSize: 10 }} label={{ value: "단기 RS →", angle: -90, position: "insideLeft", offset: 26, fontSize: 11 }} />
                <ZAxis type="number" dataKey="market_cap" range={[80, 2400]} />
                <ReferenceLine x={50} stroke="var(--border)" />
                <ReferenceLine y={50} stroke="var(--border)" />
                <Tooltip cursor={false} content={<MapTooltip />} />
                {/* hover 궤적 — 과거→현재 연결선 */}
                {trailData.length > 1 && (
                  <Scatter data={trailData} line={{ stroke: "var(--color-up)", strokeWidth: 1.5, strokeDasharray: "3 3" }}
                    fill="var(--color-up)" shape={(p: { cx?: number; cy?: number; payload?: { label?: string } }) => (
                      <g>
                        <circle cx={p.cx} cy={p.cy} r={p.payload?.label === "현재" ? 7 : 4}
                          fill="var(--color-up)" opacity={p.payload?.label === "현재" ? 0.95 : 0.55} />
                        <text x={p.cx} y={(p.cy ?? 0) + 14} textAnchor="middle" fontSize={9} fill="var(--muted-foreground)">
                          {p.payload?.label !== "현재" ? p.payload?.label : ""}
                        </text>
                      </g>
                    )} isAnimationActive={false} />
                )}
                <Scatter data={data.groups} isAnimationActive={false}
                  onMouseEnter={(g) => setHovered((g as unknown as SectorGroup).name)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={(g) => setSelected((g as unknown as SectorGroup).name)}>
                  {data.groups.map((g) => (
                    <Cell key={g.name} fill={flowColor(g.chg_5d)} stroke="var(--card)" strokeWidth={1}
                      opacity={hovered && hovered !== g.name ? 0.25 : 1} cursor="pointer" />
                  ))}
                  <LabelList dataKey="name" position="top" style={{ fontSize: 10, fill: "var(--muted-foreground)" }} />
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* 구성 테이블 */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">산업(섹터) 구성 — 클릭하면 소속 종목</CardTitle></CardHeader>
        <CardContent className="px-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="px-4 py-1.5 text-left font-medium">대분류</th>
                <th className="py-1.5 text-right font-medium">시총</th>
                <th className="py-1.5 text-right font-medium">비중</th>
                <th className="py-1.5 text-right font-medium">종목</th>
                <th className="py-1.5 text-right font-medium">5일</th>
                <th className="py-1.5 text-right font-medium">장기 RS</th>
                <th className="px-4 py-1.5 text-right font-medium">단기 RS</th>
              </tr>
            </thead>
            <tbody>
              {data.groups.map((g) => (
                <tr key={g.name}
                  className={cn("border-b border-border/50 cursor-pointer hover:bg-muted/50",
                    selected === g.name && "bg-muted/60")}
                  onClick={() => setSelected(selected === g.name ? null : g.name)}
                  onMouseEnter={() => setHovered(g.name)} onMouseLeave={() => setHovered(null)}>
                  <td className="px-4 py-1.5 font-medium">
                    <span className="inline-block h-2 w-2 rounded-full mr-2" style={{ background: flowColor(g.chg_5d) }} />
                    {g.name}
                    {(g.rs_long ?? 0) >= 80 && <Badge variant="outline" className="ml-2 text-[9px] text-up border-up/40">강세</Badge>}
                    {(g.rs_long ?? 50) <= 20 && <Badge variant="outline" className="ml-2 text-[9px] text-down border-down/40">약세</Badge>}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-xs">{formatKrw(g.market_cap)}</td>
                  <td className="py-1.5 text-right tabular-nums text-xs">{totalMcap ? `${(g.market_cap / totalMcap * 100).toFixed(0)}%` : "-"}</td>
                  <td className="py-1.5 text-right tabular-nums text-xs">{g.stocks}</td>
                  <td className={cn("py-1.5 text-right tabular-nums text-xs", g.chg_5d >= 0 ? "text-up" : "text-down")}>
                    {g.chg_5d >= 0 ? "+" : ""}{g.chg_5d}%
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-xs">{g.rs_long ?? "-"}</td>
                  <td className="px-4 py-1.5 text-right tabular-nums text-xs">{g.rs_short ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {selected && <ValueChain group={selected} onTheme={(t) => navigate(`/feed?q=${encodeURIComponent(t)}`)} />}
      {selected && <GroupMembers group={selected} onGo={(code) => navigate(`/analyze/${code}/summary`)} />}
    </PageContainer>
  )
}

interface ChainStage { stage_name: string; themes: string[] }

/** 밸류체인 — 상류→하류 단계 흐름 + 테마 칩(클릭 시 피드 검색) */
function ValueChain({ group, onTheme }: { group: string; onTheme: (theme: string) => void }) {
  const { data } = useQuery(
    apiQuery<{ group: string; stages: ChainStage[] }>({
      key: ["spine", "sector-map", "chain", group],
      url: `/api/spine/sector-map/chain?group=${encodeURIComponent(group)}`,
      staleTime: STALE.long,
    }),
  )
  if (!data || data.stages.length === 0) return null
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{group} — 산업 흐름 <span className="font-normal text-muted-foreground">(상류 → 하류 · 테마 클릭 시 피드)</span></CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <div className="flex items-stretch gap-2 min-w-max pb-1">
          {data.stages.map((st, i) => (
            <div key={i} className="flex items-stretch gap-2">
              <div className="rounded-lg border px-3 py-2 min-w-[130px] max-w-[180px]">
                <div className="text-xs font-semibold mb-1.5">{st.stage_name}</div>
                <div className="flex flex-wrap gap-1">
                  {st.themes.map((t) => (
                    <Badge key={t} variant="secondary"
                      className="text-[10px] font-normal cursor-pointer hover:bg-primary hover:text-primary-foreground"
                      onClick={() => onTheme(t)}>{t}</Badge>
                  ))}
                </div>
              </div>
              {i < data.stages.length - 1 && (
                <div className="flex items-center text-muted-foreground shrink-0">→</div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function MapTooltip({ active, payload }: { active?: boolean; payload?: { payload: SectorGroup }[] }) {
  const g = active && payload?.[0]?.payload
  if (!g || !("name" in g)) return null
  const quad = (g.rs_long ?? 50) >= 50
    ? ((g.rs_short ?? 50) >= 50 ? "주도 — 현재 시장 주도" : "과열·경계 — 강하지만 단기 수급 식는 중")
    : ((g.rs_short ?? 50) >= 50 ? "부상 — 미래 주도 후보" : "소외 — 관망")
  return (
    <div className="rounded-lg border bg-card px-3 py-2 shadow-md text-xs space-y-1 max-w-56">
      <p className="font-semibold text-sm">{g.name}</p>
      <p className="text-muted-foreground">{quad}</p>
      <p className="tabular-nums">장기 RS {g.rs_long} · 단기 RS {g.rs_short}</p>
      <p className="tabular-nums">시총 {formatKrw(g.market_cap)} · {g.stocks}종목 ·{" "}
        <span className={g.chg_5d >= 0 ? "text-up" : "text-down"}>5일 {g.chg_5d >= 0 ? "+" : ""}{g.chg_5d}%</span>
      </p>
    </div>
  )
}

function GroupMembers({ group, onGo }: { group: string; onGo: (code: string) => void }) {
  const { data, isLoading } = useQuery(
    apiQuery<{ group: string; items: MemberRow[] }>({
      key: ["spine", "sector-map", "members", group],
      url: `/api/spine/sector-map/members?group=${encodeURIComponent(group)}`,
      staleTime: STALE.medium,
    }),
  )
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{group} — 소속 종목 <span className="font-normal text-muted-foreground">(RS는 전 종목 대비 백분위)</span></CardTitle>
      </CardHeader>
      <CardContent className="px-0 overflow-x-auto">
        {isLoading ? <div className="px-4 py-3"><Skeleton className="h-5 w-full" /></div> : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="px-4 py-1.5 text-left font-medium">종목</th>
                <th className="py-1.5 text-right font-medium">시총</th>
                <th className="py-1.5 text-right font-medium">1개월</th>
                <th className="py-1.5 text-right font-medium">11개월</th>
                <th className="py-1.5 text-right font-medium">장기 RS</th>
                <th className="px-4 py-1.5 text-right font-medium">단기 RS</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((m) => (
                <tr key={m.stock_code} className="border-b border-border/50 cursor-pointer hover:bg-muted/50"
                  onClick={() => onGo(m.stock_code)}>
                  <td className="px-4 py-1.5 font-medium">{m.corp_name} <span className="text-[10px] text-muted-foreground tabular-nums">{m.stock_code}</span></td>
                  <td className="py-1.5 text-right tabular-nums text-xs">{m.market_cap ? formatKrw(m.market_cap) : "-"}</td>
                  <td className={cn("py-1.5 text-right tabular-nums text-xs", (m.ret_1m ?? 0) >= 0 ? "text-up" : "text-down")}>
                    {m.ret_1m != null ? `${m.ret_1m >= 0 ? "+" : ""}${m.ret_1m}%` : "-"}</td>
                  <td className={cn("py-1.5 text-right tabular-nums text-xs", (m.ret_12m ?? 0) >= 0 ? "text-up" : "text-down")}>
                    {m.ret_12m != null ? `${m.ret_12m >= 0 ? "+" : ""}${m.ret_12m}%` : "-"}</td>
                  <td className="py-1.5 text-right tabular-nums text-xs">{m.rs_long ?? "-"}</td>
                  <td className="px-4 py-1.5 text-right tabular-nums text-xs">{m.rs_short ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}
