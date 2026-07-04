import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

const COMPANY_TABS = [
  { key: "summary", label: "요약" },
  { key: "financials", label: "재무정보" },
  { key: "business", label: "사업정보" },
  { key: "disclosures", label: "공시/IR" },
  { key: "metrics", label: "지표차트" },
  { key: "marketcap", label: "시가총액" },
  { key: "valuation", label: "밸류에이션" },
] as const

const GLOBAL_TABS = [
  { key: "industry", label: "산업군" },
  { key: "onchain", label: "온체인" },
] as const

export type TabKey = (typeof COMPANY_TABS)[number]["key"] | (typeof GLOBAL_TABS)[number]["key"]

interface Props {
  stockCode: string | null
}

export default function TabNavigation({ stockCode }: Props) {
  const { pathname } = useLocation()

  const activeTab = getActiveTab(pathname)

  return (
    <nav className="border-b bg-card">
      <div className="mx-auto max-w-[1440px] flex px-6">
        {/* Global tabs (always visible) */}
        {GLOBAL_TABS.map((tab) => (
          <Link
            key={tab.key}
            to={`/${tab.key}`}
            className={cn(
              "px-5 py-3 text-sm border-b-2 -mb-px transition-colors cursor-pointer",
              activeTab === tab.key
                ? "font-semibold text-primary border-primary"
                : "font-normal text-muted-foreground border-transparent hover:text-foreground"
            )}
          >
            {tab.label}
          </Link>
        ))}

        {/* Separator */}
        {stockCode && <div className="w-px bg-border mx-2 my-2" />}

        {/* Company tabs (only when company selected) */}
        {stockCode && COMPANY_TABS.map((tab) => (
          <Link
            key={tab.key}
            to={`/company/${stockCode}/${tab.key}`}
            className={cn(
              "px-5 py-3 text-sm border-b-2 -mb-px transition-colors cursor-pointer",
              activeTab === tab.key
                ? "font-semibold text-primary border-primary"
                : "font-normal text-muted-foreground border-transparent hover:text-foreground"
            )}
          >
            {tab.label}
          </Link>
        ))}
      </div>
    </nav>
  )
}

function getActiveTab(pathname: string): TabKey | null {
  if (pathname.startsWith("/industry")) return "industry"
  if (pathname.startsWith("/onchain")) return "onchain"

  const companyMatch = pathname.match(/^\/company\/[^/]+\/(\w+)/)
  if (companyMatch) return companyMatch[1] as TabKey

  return null
}
