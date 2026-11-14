import { useState } from "react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { FillArea } from "@/components/shared/Bounded"
import { PagerBar, paged } from "@/components/shared/PagerBar"
import { BlockHead } from "@/components/home/HomeSection"
import { AiLine, FillNote, MarketCard, Seg } from "@/components/home/MarketFrame"
import { FillState, FlowCard, NameLink, TurnoverCard } from "@/components/home/MarketBlocks"
import { BriefingProse, kstHm, usMd } from "@/components/home/UsOvernight"
import { useUrlParam } from "@/hooks/useUrlParam"
import { useUsBriefing } from "@/hooks/useUsBriefing"
import { useCallMomentum, useRecentCalls, useSeason } from "@/hooks/useTranscripts"
import { formatNumber, formatUsd } from "@/utils/format"
import type { CallMomentumCandidate } from "@/types"
import { track } from "@/lib/usage"

/* 홈 › 미국 시장 칸(ia-redesign §4.3, 시안 Home-US) — ② 어젯밤 미국장 · ③ 새 모멘텀 후보 · ④ 최근 컨콜 */

/**
 * ② 왼쪽 — 어젯밤 미국장(Market Overnight). 요약 한 줄 → 핵심 다섯 줄 | 전문(URL ?brief=full) — 같은 높이 안에서 전환, 넘치면 칸 안 스크롤.
 * 대시보드 카드는 요약판이고 여기가 그날 정리의 정본 위치다.
 */
export function OvernightCard() {
  const q = useUsBriefing(null)
  const d = q.data
  const s = d?.synthesis
  const [view, setView] = useUrlParam("brief", "key")
  const made = kstHm(d?.synthesized_at)
  // 어젯밤 장이 아니거나 정기 생성이 실패했으면 회색 줄을 주의 색으로, 이유는 ⓘ에(옛 기준 띠)
  const fresh = !!d?.trade_date && d.trade_date === d.expected_session
  const runFailed = !!d?.last_run && d.last_run.status !== "ok"
  const why = d ? [!fresh && d.expected_session ? `어젯밤(${usMd(d.expected_session)}) 장이 아직 반영되지 않았어요.` : null,
    runFailed ? `정기 생성(06:30) 실패 — ${d.last_run!.summary ?? d.last_run!.status}` : null,
    d.status === "stale" ? `실시간 갱신 실패 — 마지막 성공 데이터입니다.${d.error ? ` (${d.error})` : ""}` : null,
    ...(s?.source_gaps?.length ? [`빠진 재료: ${s.source_gaps.join(" · ")}`] : [])].filter(Boolean) : []
  const warn = !!d && (!fresh || runFailed || d.status === "stale")
  const line = d?.trade_date ? `Market Overnight · ${usMd(d.trade_date)} 장 마감${s ? ` · 출처 ${s.sources?.length ?? 0}건` : ""}${made ? ` · ${made} 생성` : ""}` : "Market Overnight"
  const sub = <span className={warn ? "text-warn" : undefined}>{line}</span>
  const lead = (s?.drivers || s?.index_summary || s?.issues || "").replace(/\[\d+\]/g, "").split(/(?<=[.다요])\s/)[0]
  return <MarketCard band="summary" label="us.overnight" id="us-briefing">
    <BlockHead section title="어젯밤 미국장" sub={sub} info={<>미국장 마감 뒤 수집 문서와 시세로 정리합니다. 매일 06:30에 만들어집니다.{why.map(w => <span key={w} className="mt-1 block">{w}</span>)}</>}
      actions={<Seg label="브리핑 보기" value={view === "full" ? "full" : "key"} onChange={v => { if (v === "full") track("open", "overnight.full", { entity: d?.trade_date }); setView(v) }} items={[{ key: "key", label: "핵심" }, { key: "full", label: "전문" }]} />} />
    <AiLine>AI 요약 · 미국 시장 마감 정리</AiLine>
    <FillState data={d} isError={q.isError || d?.status === "error"} error={q.error} onRetry={() => void q.refetch()} message="어젯밤 미국장 브리핑을 불러오지 못했습니다">{() => !d!.movers.length
      ? <FillNote>오늘 브리핑이 아직 없어요. 매일 06:30에 만들어집니다.</FillNote>
      : !s ? <FillNote>종합 브리핑이 아직 없어요. 거래대금 쏠림은 오른쪽에 있습니다.</FillNote>
      : <>
        {lead && <p className="shrink-0 text-[15px] leading-[1.55] font-semibold text-pretty">{lead}</p>}
        <FillArea key={view} aria-label={view === "full" ? "브리핑 전문" : "핵심 다섯 줄"}>
          {view === "full" ? <BriefingProse data={d!} /> : <ol>{(s.key_points ?? []).slice(0, 5).map((p, i) => <li key={i} className="grid grid-cols-[26px_1fr] gap-1.5 border-b py-[9px] text-[13.5px] leading-[1.55]">
            <span className="pt-0.5 font-mono text-[11.5px] text-ink-3 tabular-nums">{String(i + 1).padStart(2, "0")}</span><span>{p}</span>
          </li>)}</ol>}
        </FillArea>
      </>}</FillState>
  </MarketCard>
}

/** ② 오른쪽 — 달러 거래대금 쏠림(브리핑과 같은 스냅샷) */
export function UsFlowCard() {
  const q = useUsBriefing(null)
  const d = q.data
  return <FlowCard market="us" n={d?.movers.length || 20} day={d?.trade_date ? usMd(d.trade_date) : null}
    info="달러 거래대금 상위 20종목을 업종으로 묶은 비중과 업종 대표(중앙값) 등락"
    clusters={d && d.status !== "error" ? d.clusters.map(c => ({ ...c, title: c.tickers.join(" · ") })) : null}
    state={{ isError: q.isError || d?.status === "error", error: q.error, onRetry: () => void q.refetch() }} />
}

/** ③ 왼쪽 — 미국 거래대금 상위 20. 업종 대신 '실적' 열 — 이번 시즌에 실적을 낸 종목이면 'M/D 실적 ›'으로 콜 상세 */
export function UsTurnoverCard() {
  const q = useUsBriefing(null)
  const season = useSeason()
  const d = q.data
  const earned = new Map((season.data?.reported ?? []).map(r => [r.ticker, r]))
  return <TurnoverCard market="us" middleLabel="실적" sub={d?.trade_date ? `미국 상장 · ${usMd(d.trade_date)}` : <span aria-hidden className="invisible">미국 상장 · 00/00</span>}
    state={{ isError: q.isError || d?.status === "error", error: q.error, onRetry: () => void q.refetch() }}
    rows={d && d.status !== "error" ? d.movers.slice(0, 20).map(m => {
      const e = earned.get(m.ticker)
      return { key: m.ticker, rank: m.rank, change_pct: m.change_pct, value: m.dollar_volume == null ? "-" : formatUsd(m.dollar_volume),
        name: <><NameLink to={`/us/${m.ticker}`} mono>{m.ticker}</NameLink><span className="truncate font-sans text-xs text-ink-3">{m.name}</span></>,
        middle: e ? <Badge asChild><Link to={e.transcript_id ? `/follow/transcripts?t=${e.transcript_id}` : `/us/${m.ticker}`}>{usMd(e.event_date)} 실적 ›</Link></Badge> : null }
    }) : null} />
}

/** ③ 오른쪽 — 새 모멘텀 후보(D-310). 새로 붙은 | 이어지는(URL ?mom=cont). 줄을 누르면 실적 시즌의 선택한 후보 */
export function MomentumCard() {
  const q = useCallMomentum()
  const d = q.data
  const [tab, setTab] = useUrlParam("mom", "new")
  const list: CallMomentumCandidate[] = d ? (tab === "cont" ? d.continuing ?? [] : d.candidates) : []
  return <MarketCard band="stocks" label="us.momentum">
    <BlockHead section title="새 모멘텀 후보" sub={d ? `이번 시즌 ${formatNumber(d.candidates.length)}` : <span aria-hidden className="invisible">이번 시즌 00</span>}
      info="기대 초과 가속·가이던스 상향·수요 어조로 고른 후보입니다. 실적 시즌 개요의 '새 모멘텀 후보'와 같은 판정입니다"
      actions={<Seg label="모멘텀 보기" value={tab === "cont" ? "cont" : "new"} onChange={setTab} items={[{ key: "new", label: "새로 붙은" }, { key: "cont", label: "이어지는" }]} />} />
    <FillState data={d} isError={q.isError} error={q.error} onRetry={() => void q.refetch()} message="새 모멘텀 후보를 불러오지 못했습니다">{() => !list.length
      ? <FillNote>{tab === "cont" ? "이번 시즌 이어지는 모멘텀이 아직 없어요." : d!.season.reported ? "이번 시즌 새 모멘텀으로 판정된 곳이 아직 없어요." : "이번 시즌 발표가 아직 분석되지 않았어요."}</FillNote>
      : <FillArea aria-label="새 모멘텀 후보"><ul>{[...list].sort((a, b) => b.score - a.score).map(c => {
        const lead = c.summary ?? (c.drivers.find(x => x.status === "new") ?? c.drivers.find(x => x.status === "accelerating"))?.name ?? ""
        return <li key={`${c.ticker}-${c.event_date}`} className="border-b py-2.5">
          <Link to={`/follow/transcripts?view=season&pick=${c.ticker}#momentum`} className="flex flex-col gap-1 hover:[&_.tk]:underline">
            <span className="flex items-center gap-2">
              <span className="tk font-mono text-[13.5px] font-medium">{c.ticker}</span>
              <span className="min-w-0 truncate text-xs text-ink-3">{c.name}</span>
              <span className="ml-auto shrink-0 font-mono text-[11.5px] text-ink-3">{usMd(c.event_date)}</span>
            </span>
            {lead && <span className="line-clamp-2 text-[12.5px] leading-[1.6] text-ink-2">{lead}</span>}
          </Link>
        </li>
      })}</ul></FillArea>}</FillState>
    <Link to="/follow/transcripts?view=season#momentum" className="shrink-0 text-[12.5px] font-medium text-ink-2 hover:text-ink">실적 시즌 › 모멘텀 ›</Link>
  </MarketCard>
}

/** ④ 오른쪽 — 최근 컨콜(지난 7일 받은 콜, 발표일 순, 6개씩 페이지). 누르면 콜 상세 */
export function CallsCard() {
  const q = useRecentCalls(7)
  const [page, setPage] = useState(0)
  const rows = q.data ? [...q.data].sort((a, b) => (b.call_date ?? "").localeCompare(a.call_date ?? "")) : []
  const pg = paged(rows, page, 6)
  return <MarketCard band="events" label="us.calls">
    <BlockHead section title="최근 컨콜" sub={q.data ? `최근 7일 ${formatNumber(q.data.length)}건` : <span aria-hidden className="invisible">최근 7일 00건</span>}
      info="녹취록을 받은 콜. 누르면 콜 상세(발표 전 시장이 주목한 내용·반응)로 갑니다. 매일 07:20에 수집합니다" link={{ to: "/follow/transcripts", label: "컨콜 전체" }} />
    <FillState data={q.data} isError={q.isError} error={q.error} onRetry={() => void q.refetch()} message="최근 컨콜을 불러오지 못했습니다" rows={6}>{() => !rows.length
      ? <FillNote>지난 7일간 새로 받은 컨콜이 없어요. 매일 07:20에 수집합니다.</FillNote>
      : <>
        <FillArea aria-label="최근 컨콜 목록"><ul>{pg.rows.map(c => <li key={c.transcript_id} className="border-b">
          <Link to={`/follow/transcripts?t=${c.transcript_id}`} className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-2.5 py-2.5 hover:[&_.tk]:underline">
            <span className="font-mono text-[11.5px] text-ink-3">{c.call_date ? usMd(c.call_date) : "-"}</span>
            <span className="flex min-w-0 items-baseline gap-2"><span className="tk font-mono text-[13.5px] font-medium">{c.ticker}</span><span className="truncate text-[12.5px] text-ink-2">{c.company_name}</span></span>
            <Badge>{`${c.fiscal_period} FY${String(c.fiscal_year).slice(2)}`}</Badge>
          </Link>
        </li>)}</ul></FillArea>
        <PagerBar {...pg} onPage={setPage} label="최근 컨콜 페이지" />
      </>}</FillState>
  </MarketCard>
}
