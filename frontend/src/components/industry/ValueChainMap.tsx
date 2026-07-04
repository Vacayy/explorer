import { useMemo } from "react"
import { formatKrw } from "@/utils/format"
import type { IndustryMember } from "@/types"

interface Props {
  members: IndustryMember[]
  onSelectCompany: (m: IndustryMember) => void
}

// Category display config — ordered by value chain flow
const CATEGORY_CONFIG: Record<string, { label: string }> = {
  "1_설계(Fabless)":  { label: "설계" },
  "2_소재/웨이퍼":      { label: "소재/웨이퍼" },
  "3_전공정장비":       { label: "전공정장비" },
  "4_IDM/파운드리":     { label: "IDM/파운드리" },
  "5_후공정장비":       { label: "후공정장비" },
  "6_패키징/OSAT":    { label: "패키징" },
  "7_테스트/검사":      { label: "테스트" },
}

const FLOW_ORDER = [
  "1_설계(Fabless)", "2_소재/웨이퍼", "3_전공정장비",
  "4_IDM/파운드리", "5_후공정장비", "6_패키징/OSAT", "7_테스트/검사",
]

export default function ValueChainMap({ members, onSelectCompany }: Props) {
  const grouped = useMemo(() => {
    const result: Record<string, IndustryMember[]> = {}
    for (const m of members) {
      if (!result[m.category]) result[m.category] = []
      result[m.category].push(m)
    }
    // Sort by market cap desc within each
    for (const cat of Object.keys(result)) {
      result[cat].sort((a, b) => (b.latest_market_cap ?? 0) - (a.latest_market_cap ?? 0))
    }
    return result
  }, [members])

  // Max market cap for bubble sizing
  const maxMcap = useMemo(() => {
    // Exclude top 2 (삼성전자, SK하이닉스) for better scaling
    const mcaps = members
      .map((m) => m.latest_market_cap ?? 0)
      .sort((a, b) => b - a)
    return mcaps[2] ?? mcaps[0] ?? 1
  }, [members])

  return (
    <div className="space-y-1">
      {/* Flow arrow header */}
      <div className="flex items-center gap-0 px-2 mb-3 overflow-x-auto flex-wrap">
        {FLOW_ORDER.map((cat, i) => {
          const cfg = CATEGORY_CONFIG[cat]
          if (!cfg) return null
          const count = grouped[cat]?.length ?? 0
          return (
            <span key={cat} className="flex items-center shrink-0">
              <span className="text-sm font-medium text-foreground whitespace-nowrap">
                {cfg.label} ({count})
              </span>
              {i < FLOW_ORDER.length - 1 && (
                <span className="text-sm text-muted-foreground mx-2">→</span>
              )}
            </span>
          )
        })}
      </div>

      {/* Value chain cards */}
      <div className="grid grid-cols-7 gap-2">
        {FLOW_ORDER.map((cat) => {
          const cfg = CATEGORY_CONFIG[cat]
          const items = grouped[cat] ?? []
          if (!cfg) return null

          return (
            <div key={cat} className="min-w-0">
              {/* Category header */}
              <div className="text-xs font-semibold px-2 py-1.5 bg-muted/50 text-foreground border-b text-center border-l-2 border-l-primary rounded-t-sm">
                {cfg.label}
              </div>

              {/* Company list */}
              <div className="border border-t-0 rounded-b-md bg-card p-1 space-y-0.5 min-h-[120px]">
                {items.map((m) => {
                  const mcap = m.latest_market_cap ?? 0
                  const hasMcap = mcap > 0

                  // Bubble size: min 20px, max 40px based on market cap
                  const isGiant = mcap > maxMcap * 2
                  const ratio = isGiant ? 1 : Math.min(mcap / maxMcap, 1)
                  const size = Math.max(20, Math.round(20 + ratio * 20))

                  return (
                    <div
                      key={m.id}
                      className="flex items-center gap-1.5 px-1.5 py-1 rounded cursor-pointer hover:bg-accent transition-colors group"
                      onClick={() => onSelectCompany(m)}
                      title={`${m.corp_name} (${m.stock_code})\n시가총액: ${formatKrw(mcap)}\n현재가: ${m.latest_close?.toLocaleString()}원`}
                    >
                      {/* Size indicator dot */}
                      {hasMcap ? (
                        <div
                          className="rounded-full shrink-0 flex items-center justify-center bg-secondary"
                          style={{ width: size, height: size }}
                        >
                          <span className="text-[7px] font-medium text-muted-foreground">
                            {mcap >= 1e12 ? `${(mcap / 1e12).toFixed(0)}조` : mcap >= 1e8 ? `${Math.round(mcap / 1e8)}억` : ""}
                          </span>
                        </div>
                      ) : (
                        <div
                          className="rounded-full shrink-0 bg-muted"
                          style={{ width: 20, height: 20 }}
                        />
                      )}

                      {/* Name */}
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] font-semibold truncate group-hover:text-primary">
                          {m.corp_name}
                        </div>
                        {hasMcap && (
                          <div className="text-[9px] text-muted-foreground">
                            {formatKrw(mcap)}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
