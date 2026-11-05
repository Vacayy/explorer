import { Link } from "react-router-dom"
import { ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { WidgetState } from "@/components/shared/WidgetFrame"
import { DropletContent, DropletReveal, DropletTrigger } from "@/components/shared/DropletReveal"
import { CitedText, UsBriefingSection } from "@/components/home/UsBriefingSection"
import { useUsBriefing } from "@/hooks/useUsBriefing"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"
import type { UsBriefing, UsCluster, UsMoverBrief } from "@/types"

/** 한국 관례: 상승 빨강·하락 파랑 */
const tone = (v: number | null | undefined) => v == null || v === 0 ? "" : v > 0 ? "text-up-ink" : "text-down-ink"
/** 'YYYY-MM-DD' → 'M/D' */
export const usMd = (d: string | null | undefined) => d ? `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}` : "-"
/** SQLite UTC('YYYY-MM-DD HH:MM:SS') → KST 'HH:MM' */
export const kstHm = (utc: string | null | undefined) => {
  if (!utc) return null
  const t = new Date(utc.includes("T") ? utc : `${utc.replace(" ", "T")}Z`)
  return Number.isNaN(t.getTime()) ? null : t.toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false })
}

/** 거래대금 쏠림 상위 n — 유리 상자 · 라벨 110 · 6px 막대(ink) · 비중 · 대표 등락 (시안 Home·Home-US) */
export function FlowBars({ clusters, n = 3 }: { clusters: UsCluster[]; n?: number }) {
  if (clusters.length === 0) return null
  return <div className="glass flex flex-col gap-1.5 rounded-2xl px-3.5 py-3" data-us-flow>
    <span className="text-[11.5px] text-ink-2">거래대금 쏠림 · 상위 20</span>
    {clusters.slice(0, n).map(c => (
      <div key={c.label} className="grid grid-cols-[110px_1fr_48px_52px] items-center gap-2 text-[12.5px]">
        <span className="truncate">{c.label}</span>
        <div className="h-1.5 rounded-[3px] bg-chip"><div className="h-full rounded-[3px] bg-ink" style={{ width: `${Math.min(100, c.share_pct)}%` }} /></div>
        <span className="font-mono text-xs tabular-nums">{Math.round(c.share_pct)}%</span>
        <span className={cn("text-right font-mono text-xs tabular-nums", tone(c.median_change))}>{formatPercent(c.median_change)}</span>
      </div>
    ))}
  </div>
}

/** 그룹으로 안 풀리는 움직임 — 유리 알약(티커 · 등락) → 미국 도시에 */
export function LoneMoverChips({ movers }: { movers: UsMoverBrief[] }) {
  if (movers.length === 0) return null
  return <div className="flex flex-col gap-1.5">
    <span className="text-[11.5px] text-ink-2">그룹으로 안 풀리는 움직임</span>
    <div className="flex flex-wrap gap-1.5">
      {movers.map(m => (
        <Link key={m.ticker} to={`/us/${m.ticker}`} title={m.headlines?.[0]?.title ?? m.name}
          className="glass inline-flex h-[26px] items-baseline gap-1.5 rounded-full px-2.5 pt-[5px] text-xs hover:opacity-80">
          <span className="font-mono font-medium tabular-nums">{m.ticker}</span>
          <span className={cn("font-mono tabular-nums", tone(m.change_pct))}>{formatPercent(m.change_pct)}</span>
        </Link>
      ))}
    </div>
  </div>
}

/** 브리핑 전문 — 매크로 · 거래대금으로 본 기업 이슈 · 스터디/공유 후보 · 출처 (시안 Home 물방울 · Home-US 왼쪽) */
export function BriefingProse({ data }: { data: UsBriefing }) {
  const s = data.synthesis
  if (!s) return null
  const sources = s.sources ?? []
  const paras = (fields: (string | undefined)[]) => fields.filter(Boolean)
    .flatMap(f => (f as string).split(/\n{2,}/).map(p => p.trim()).filter(Boolean))
  const macro = paras([s.index_summary, s.drivers]), biz = paras([s.issues])
  const section = (label: string, ps: string[]) => ps.length > 0 && <div className="flex flex-col gap-2">
    <span className="text-[11.5px] text-ink-3">{label}</span>
    {ps.map((p, i) => <p key={i} className="text-sm leading-[1.75] text-pretty"><CitedText text={p} sources={sources} /></p>)}
  </div>
  const cands = [["스터디 후보", s.study_candidates], ["공유 후보", s.share_candidates]] as const
  return <div className="flex flex-col gap-3.5">
    {section("매크로", macro)}
    {section("거래대금으로 본 기업 이슈", biz)}
    {(s.study_candidates.length > 0 || s.share_candidates.length > 0) && <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr))]">
      {cands.filter(([, xs]) => xs.length > 0).map(([t, xs]) => <div key={t} className="flex flex-col gap-1.5 rounded-xl bg-chip px-3.5 py-3">
        <span className="text-xs font-semibold">{t}</span>
        {xs.map((x, i) => <p key={i} className="text-[12.5px] leading-[1.55] text-ink-2">{x}</p>)}
      </div>)}
    </div>}
    {sources.length > 0 && <div>
      <span className="text-[11.5px] text-ink-3">출처</span>
      <ul className="mt-1">{sources.map(src => <li key={src.n} className="py-[3px] text-xs text-ink-2">
        <span className="font-mono text-[11px] text-ink-3 tabular-nums">[{src.n}]</span> {src.publisher}{src.title ? ` · ${src.title}` : ""}
      </li>)}</ul>
    </div>}
  </div>
}

/**
 * 홈 › 대시보드 Market Overnight 본문(시안 Home) — 한 줄 요지 · 핵심 01~05 · 거래대금 쏠림 3줄 · 그룹으로 안 풀리는 움직임 칩 ·
 * '브리핑 전체 보기' → 물방울로 칸 안에서 전문이 올라온다(ia-redesign §4.1). LLM 종합이 없는 날은 전문 자리에 구조화 브리핑.
 */
export function UsOvernightBody() {
  const q = useUsBriefing(null)
  const d = q.data
  if (!d) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (d.status === "error") return <WidgetState error onRetry={() => void q.refetch()} />
  if (d.movers.length === 0) return <WidgetState empty emptyText="오늘 브리핑이 아직 없어요. 매일 06:30에 만들어집니다." />
  const s = d.synthesis
  const lead = (s?.drivers || s?.index_summary || s?.issues || "").replace(/\[\d+\]/g, "").split(/(?<=[.다요])\s/)[0]
  // 물방울은 칸 전체(머리 포함)를 덮는다 — 기준 상자는 바깥 칸(relative), 여기는 static
  return <DropletReveal className="static flex h-full flex-col gap-3.5 overflow-visible">
    {lead && <p className="text-[17px] leading-[1.55] font-medium text-pretty">{lead}</p>}
    {!!s?.key_points?.length && <ol>
      {s.key_points.slice(0, 5).map((p, i) => <li key={i} className="grid grid-cols-[22px_1fr] gap-1.5 border-t py-[7px] text-[13.5px] leading-[1.55] first:border-t-0">
        <span className="font-mono text-[11.5px] text-ink-3 tabular-nums">{String(i + 1).padStart(2, "0")}</span><span>{p}</span>
      </li>)}
    </ol>}
    <FlowBars clusters={d.clusters} />
    <LoneMoverChips movers={d.idiosyncratic.slice(0, 4)} />
    <DropletTrigger asChild>
      <Button variant="outline" className="glass mt-auto h-11 w-full shrink-0 rounded-full text-sm font-medium">브리핑 전체 보기 <ChevronDown aria-hidden /></Button>
    </DropletTrigger>
    <DropletContent className="rounded-[16px]" title="브리핑 전체" description={`어젯밤 미국장 · ${usMd(d.trade_date)} 장 마감${s ? ` · 출처 ${s.sources?.length ?? 0}건` : ""}`}>
      {s ? <BriefingProse data={d} /> : <div className="@container/market"><UsBriefingSection embedded /></div>}
    </DropletContent>
  </DropletReveal>
}
