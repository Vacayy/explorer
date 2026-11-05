import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { InfoTip } from "@/components/shared/InfoTip"
import { useActions } from "@/hooks/useActions"
import { useTradeByStock } from "@/hooks/useTrade"
import { useTwLinks } from "@/hooks/useTwRevenue"
import { TW_RELATION } from "@/components/shared/TwLinkSignal"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { TradeFlag, TwLink } from "@/types"

const TRADE_LABEL: Record<TradeFlag, string> = { surge: "수출 급증", plunge: "수출 급감", new: "수출 신규", none: "수출" }
const tone = (dir: "up" | "down" | null) => dir === "up" ? "bg-up-tint text-up-ink" : dir === "down" ? "bg-down-tint text-down-ink" : "bg-chip text-ink-2"
const twDir = (s: TwLink["state"]) => s === "가속" || s === "전환↑" ? "up" : s === "둔화" || s === "전환↓" ? "down" : null
const valueTone = (v: number | null) => v == null ? "text-muted-foreground" : v > 0 ? "text-up-ink" : v < 0 ? "text-down-ink" : ""

/**
 * 국내 도시에 개요 오른쪽 '연결 신호' (시안 Dossier-KR) — 한 줄 행: 배지 | 내용 | 수치.
 * 수출입 품목(이 종목을 관련 종목으로 지목한 품목) · 대만 연결 회사 월매출 · 최근 30일 기업활동.
 * 셋 다 없으면 그리지 않는다(대부분 종목이 해당 없음).
 */
export function DossierLinkSignals({ stockCode }: { stockCode: string }) {
  const trade = useTradeByStock(stockCode)
  const tw = useTwLinks(stockCode)
  const actions = useActions({ stockCode, days: 30 })
  if (trade.isLoading || tw.isLoading || actions.isLoading) return <Skeleton className="h-36 w-full rounded-card" />
  const items = trade.data ?? []
  const links = tw.data?.items ?? []
  const acts = (actions.data?.items ?? []).filter((a) => !a.is_correction)
  const failed = trade.isError || tw.isError || actions.isError
  if (!items.length && !links.length && !acts.length && !failed) return null
  const period = items[0]?.period
  const twMonth = tw.data?.as_of ? Number(tw.data.as_of.slice(5, 7)) : null
  const caption = [period && `${period} 통계`, links.length && twMonth && `대만 ${twMonth}월 공시`].filter(Boolean).join(" · ")
  const types = [...new Set(acts.map((a) => a.action_type))]
  return (
    <Card className="min-w-0 gap-0 py-0" aria-label="연결 신호">
      <header className="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-1 px-4 pt-4">
        <h2 className="text-section font-semibold">연결 신호</h2>
        {caption && <span className="text-caption text-muted-foreground">{caption}</span>}
        <InfoTip label="연결 신호 설명">수출입 품목과 대만 연결 회사 월매출은 업황 방향 신호입니다. 이 종목의 매출 전망이 아니며, 서버 ODM 매출에는 GPU 매입 원가가 섞여 있습니다.</InfoTip>
      </header>
      <ul className="px-4 pb-2 pt-1.5">
        {items.slice(0, 2).map((t) => (
          <Row key={t.hs_code} badge={TRADE_LABEL[t.flag ?? "none"]} dir={t.flag === "surge" ? "up" : t.flag === "plunge" ? "down" : null}
            value={formatPercent(t.yoy_pct)} valueTone={valueTone(t.yoy_pct)} title={t.reason ?? undefined}>
            <Link to={`/follow/trade?hs=${encodeURIComponent(t.hs_code)}`} className="hover:underline">{t.item_name}{t.rel ? ` · ${t.rel}` : ""}</Link>
          </Row>
        ))}
        {trade.isError && <Row badge="수출" dir={null}><span className="text-muted-foreground">불러오지 못했습니다</span></Row>}
        {links.slice(0, 2).map((l) => (
          <Row key={`${l.relation}-${l.tw.map((t) => t.code).join("")}`} badge={`대만${l.state ? ` ${l.state}` : ""}`} dir={twDir(l.state)}
            value={formatPercent(l.yoy_3m)} valueTone={valueTone(l.yoy_3m)}
            title={`${TW_RELATION[l.relation]} · ${l.reason} · 3개월 YoY${l.yoy_3m_prev != null ? ` (3개월 전 ${formatPercent(l.yoy_3m_prev)})` : ""}`}>
            <Link to="/follow/taiwan" className="hover:underline">{l.tw.map((t) => t.name).join("·")} 월매출 YoY · 사업 근거 {l.confidence}</Link>
          </Row>
        ))}
        {tw.isError && <Row badge="대만" dir={null}><span className="text-muted-foreground">불러오지 못했습니다</span></Row>}
        <Row badge="기업활동" dir={null}>
          {actions.isError ? <span className="text-muted-foreground">불러오지 못했습니다</span>
            : acts.length ? <Link to={`/analyze/${stockCode}/summary#actions`} className="hover:underline">최근 30일 {types.slice(0, 3).join("·")} {acts.length}건</Link>
            : <span className="text-ink-2">최근 30일 공시 없음</span>}
        </Row>
      </ul>
    </Card>
  )
}

function Row({ badge, dir, value, valueTone, title, children }: { badge: string; dir: "up" | "down" | null; value?: string; valueTone?: string; title?: string; children: ReactNode }) {
  return (
    <li className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-1 border-t py-2.5 first:border-t-0" title={title}>
      <span className={cn("inline-flex h-[22px] items-center whitespace-nowrap rounded-md px-2 text-xs font-medium", tone(dir))}>{badge}</span>
      <span className="min-w-0 truncate text-[13px]">{children}</span>
      {value ? <span className={cn("font-mono text-[13px] tabular-nums", valueTone)}>{value}</span> : <span />}
    </li>
  )
}
