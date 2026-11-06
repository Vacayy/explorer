import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { FillArea } from "@/components/shared/Bounded"
import { BlockHead } from "@/components/home/HomeSection"
import { tone } from "@/components/home/blockState"
import { AiLine, FillNote, KpiStrip, MarketCard, Seg } from "@/components/home/MarketFrame"
import { FillState, FlowCard, NameLink, TurnoverCard } from "@/components/home/MarketBlocks"
import { tradeIsLagging } from "@/lib/trade"
import { RegimeBadge, metricValue } from "@/components/retail/retailFormat"
import { EventList, StageBadge, TrendEvidenceDialog } from "@/components/widgets/trend"
import { SCHEDULE, TopicRow, kstToday } from "@/components/widgets/marketToday"
import { mmdd } from "@/components/follow/season/seasonUi"
import { useUrlParam } from "@/hooks/useUrlParam"
import { useKrMovers } from "@/hooks/useKrMovers"
import { useMarketToday } from "@/hooks/useMarketToday"
import { useRetailSummary } from "@/hooks/useRetail"
import { useTradeHighlights } from "@/hooks/useTrade"
import { useTrendLeaders } from "@/hooks/useTrendLeaders"
import { useKrSeason } from "@/hooks/useTranscripts"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber, formatPercent, formatRatio, formatUsd } from "@/utils/format"

/* 홈 › 한국 시장 칸(ia-redesign §4.2, 시안 Home-KR) — ② Market Today · ③ 가파른 추세 · ④ 국내 실적 시즌 · ⑤ 개인 투자 열기 | 수출입 */

const md = (d: string | null | undefined) => d ? mmdd(d) : "-"
const WD = ["일", "월", "화", "수", "목", "금", "토"]
const mdw = (d: string) => `${mmdd(d)}(${WD[new Date(`${d}T12:00:00Z`).getUTCDay()]})`
const daysTo = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000)

/**
 * ② 왼쪽 — 오늘 시장 이야기(Market Today). 회차 칩(09:30 · 11:30 · 15:00 · 16:00 마감, URL ?mtslot=) → AI 줄 → 화두 목록(칸 안 스크롤).
 * 첫 회차 전에는 머리·칩을 그대로 두고 목록 자리에만 한 줄(§4.2 빈 상태).
 */
export function MarketTodayCard() {
  const [slotParam, setSlot] = useUrlParam("mtslot", "")
  const latest = useMarketToday(null, null)
  const q = useMarketToday(slotParam || null, null)
  const d = q.data ?? latest.data
  const c = d?.current
  const isToday = d?.trade_date === kstToday()
  const done = new Map((latest.data?.slots ?? []).map(s => [s.label.replace(" 마감", ""), s.slot]))
  const items = isToday || !latest.data?.slots.length
    ? SCHEDULE.map(t => ({ key: done.get(t) ?? `pending-${t}`, label: t === "16:00" ? "16:00 마감" : t, disabled: !done.has(t) }))
    : latest.data.slots.map(s => ({ key: s.slot, label: s.label }))
  const sub = c ? `Market Today · 텔레그램 ${formatNumber(c.telegram)} · 뉴스 ${formatNumber(c.news)}` : "Market Today"
  return <MarketCard band="summary" label="kr.today">
    <BlockHead section title="오늘 시장 이야기" info="장중 실시간 소스(텔레그램·뉴스)에서 주로 나온 얘기를 회차마다 정리합니다" sub={sub}
      actions={<Seg label="정리 회차" value={c?.slot ?? ""} items={items} onChange={v => setSlot(v === latest.data?.current?.slot ? "" : v)} />} />
    <AiLine>AI 요약{c ? ` · ${c.label} 정리` : d?.next_slot ? ` · 다음 정리 ${d.next_slot}` : ""}{!isToday && d?.trade_date ? ` · ${mdw(d.trade_date)}` : ""}</AiLine>
    <FillState data={d} isError={q.isError && latest.isError} error={q.error} onRetry={() => void q.refetch()} message="오늘 시장 이야기를 불러오지 못했습니다">{() => !c
      ? <FillNote>{isToday && d!.next_slot ? `오늘 첫 정리는 ${d!.next_slot}에 나와요.` : "이날은 장중 정리가 없어요."}</FillNote>
      : !c.topics.length ? <FillNote>이 회차에는 출처로 확인된 화두가 없어요.</FillNote>
      : <FillArea aria-label="오늘 시장 이야기 목록"><ul className="divide-y">{c.topics.map(t => <TopicRow key={t.title} t={t} compact={false} links={c.links_ready} full />)}</ul></FillArea>}
    </FillState>
  </MarketCard>
}

/** ② 오른쪽 — 국장 거래대금 쏠림(원천 /api/spine/kr/movers, D-108) */
export function KrFlowCard() {
  const q = useKrMovers()
  const d = q.data
  const ok = d && d.status !== "error"
  return <FlowCard market="kr" n={d?.items.length || 20} day={d?.trade_date ? md(d.trade_date) : null}
    info="거래대금 상위 20종목을 업종으로 묶은 비중과 업종 대표(중앙값) 등락. 비중은 상위 20종목 합계 기준이고 평일 16:20에 받습니다"
    clusters={ok ? d.clusters.map(c => ({ ...c, to: `/map?group=${encodeURIComponent(c.label)}`, title: c.names.join(" · ") })) : null}
    state={{ isError: q.isError || d?.status === "error", error: q.error, onRetry: () => void q.refetch() }} />
}

/** ③ 왼쪽 — 국장 거래대금 상위 20(# · 종목 + 급등락·신규 진입 배지 · 업종 · 등락 · 거래대금) */
export function KrTurnoverCard() {
  const q = useKrMovers()
  const d = q.data
  const ok = d && d.status !== "error"
  return <TurnoverCard market="kr" middleLabel="업종" sub={d?.trade_date ? `코스피·코스닥 · ${md(d.trade_date)}` : <span aria-hidden className="invisible">코스피·코스닥 · 00/00</span>}
    state={{ isError: q.isError || d?.status === "error", error: q.error, onRetry: () => void q.refetch() }}
    rows={ok ? d.items.map(m => {
      const flag = m.flags[0] ?? (m.is_new ? "신규 진입" : null)
      return { key: m.stock_code, rank: m.rank, change_pct: m.change_pct, value: formatKrw(m.value_traded), middle: m.sector ?? "-",
        name: <><NameLink to={`/analyze/${m.stock_code}/summary`}>{m.name}</NameLink>{flag && <Badge>{flag}</Badge>}</> }
    }) : null} />
}

/**
 * ③ 오른쪽 — 가파른 추세(pipeline/trend_leaders). 탭 추세 | 신고가·매물대(URL trend_tab), 종목을 누르면 근거 창(URL trend).
 * 줄 = 이름 · 업종 · 꾸준함 · ADX | 60일 추이 | 60일 수익률.
 */
export function TrendCard() {
  const q = useTrendLeaders()
  const d = q.data
  const [tab, setTab] = useUrlParam("trend_tab", "trend")
  const [code, setCode] = useUrlParam("trend", "")
  const picked = d?.items.find(i => i.stock_code === code)
  return <MarketCard band="stocks" label="kr.trend">
    <BlockHead section title="가파른 추세" sub={d ? `${formatNumber(d.universe)}종목 중 ${formatNumber(d.passed)}` : <span aria-hidden className="invisible">000종목 중 0</span>}
      info={d ? `${d.criteria} · 순위는 60일 수익률×꾸준함 · 종목을 누르면 조건별 실제 값과 차트를 봅니다` : "시총 3,000억+ · 60거래일 +30%+ · 상승 고름 · 정배열 · ADX 25+"}
      actions={<Seg label="추세 보기" value={tab === "events" ? "events" : "trend"} onChange={setTab}
        items={[{ key: "trend", label: "추세" }, { key: "events", label: "신고가·매물대" }]} />} />
    <FillState data={d} isError={q.isError} error={q.error} onRetry={() => void q.refetch()} message="가파른 추세를 불러오지 못했습니다">{() => tab === "events"
      ? <div className="min-h-0 flex-1"><EventList events={d!.events} short={false} /></div>
      : !d!.items.length ? <FillNote>오늘은 조건 다섯 개를 모두 통과한 종목이 없습니다.</FillNote>
      : <FillArea aria-label="가파른 추세 종목"><ul>{d!.items.slice(0, 20).map(t => <li key={t.stock_code} className="border-b">
        <Button variant="ghost" onClick={() => setCode(t.stock_code)} aria-label={`${t.name} 추세 근거 보기`}
          className="grid h-auto w-full grid-cols-[minmax(0,1fr)_92px_64px] items-center gap-2.5 rounded-none px-0 py-[9px] text-left font-normal hover:bg-transparent">
          <span className="min-w-0">
            <span className="flex items-center gap-1.5"><span className="truncate text-[13.5px] font-medium">{t.name}</span>{t.high52 && <StageBadge s={t.high52} />}{t.new && <Badge>신규</Badge>}</span>
            <span className="block truncate text-[11.5px] text-ink-3">{t.sector ?? "-"} · 꾸준함 {t.r2.toFixed(2)} · ADX {Math.round(t.adx)}</span>
          </span>
          <MiniSpark vals={t.spark} />
          <span className="text-right font-mono text-[13px] text-up-ink tabular-nums">{formatPercent(t.ret_60)}</span>
        </Button>
      </li>)}</ul></FillArea>}
    </FillState>
    {d && <TrendEvidenceDialog item={picked} criteria={d.criteria} onClose={() => setCode("")} />}
  </MarketCard>
}

function MiniSpark({ vals }: { vals: number[] }) {
  if (vals.length < 2) return <span />
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * 92).toFixed(1)},${(24 - (v - lo) / ((hi - lo) || 1) * 22).toFixed(1)}`).join(" ")
  // 버튼 안 svg 기본 크기(size-4)를 쓰지 않게 — 'size-' 클래스가 있으면 버튼 규칙이 빠진다
  return <svg viewBox="0 0 92 26" aria-hidden className="size-auto" style={{ width: 92, height: 26 }}><polyline points={pts} fill="none" className="stroke-up" strokeWidth="1.4" vectorEffect="non-scaling-stroke" /></svg>
}

/**
 * ④ 왼쪽 — 국내 실적 시즌 요약(원천 /api/spine/transcript/season/kr, §4.22). 발표 · 업종보다 강했다 · 이번 주 · 마감 D-n →
 * 업종별 반응(칸 안 스크롤) → 곧 발표 칩. 이번 시즌 공시가 아직 없으면(시즌 사이) 한 줄 + 지난 시즌 마감 결과 링크.
 */
export function KrSeasonCard() {
  const q = useKrSeason(null)
  const d = q.data
  const all = "/follow/transcripts?view=season&market=kr"
  return <MarketCard band="events" label="kr.season">
    <BlockHead section title={d?.season.label ?? "국내 실적 시즌"} sub="국내 · 잠정실적·분기보고서" info="발표 후 첫 거래일 같은 업종 중앙값 대비 초과 수익(x1)으로 판정합니다" link={{ to: all, label: "국내 실적 시즌 전체" }} />
    <FillState data={d} isError={q.isError} error={q.error} onRetry={() => void q.refetch()} message="국내 실적 시즌을 불러오지 못했습니다">{() => {
      const k = d!.kpi
      if (!d!.announcements.length) {
        const prev = [...d!.seasons].reverse().find(s => s.key < d!.season.key && s.count > 0)
        return <div data-season-state="between" className="flex min-h-0 flex-1 flex-col gap-2 text-sm">
          <p className="text-ink-2">아직 이번 시즌 잠정실적 공시가 없습니다.</p>
          {prev && <Link to={`${all}&season=${prev.key}`} className="text-[12.5px] font-medium text-ink-2 hover:text-ink">{prev.label} 마감 결과 보기 ›</Link>}
        </div>
      }
      const dleft = daysTo(d!.today, d!.deadline)
      return <>
        <KpiStrip items={[
          { label: "발표", value: formatNumber(k.reported), of: `/ 지난 시즌 ${formatNumber(k.prev_reported)}` },
          { label: "업종보다 강했다", value: k.outperform_ratio == null ? "-" : `${Math.round(k.outperform_ratio)}%`, of: `${formatNumber(k.outperform_n)} / ${formatNumber(k.outperform_base)}` },
          { label: "이번 주 발표", value: k.week ? formatNumber(k.week.n) : "-", of: k.week?.first && k.week.last ? `${md(k.week.first)}–${md(k.week.last)}` : undefined },
          { label: "마감", value: dleft > 0 ? `D-${dleft}` : dleft === 0 ? "오늘" : "마감", of: mdw(d!.deadline) },
        ]} />
        <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_54px_1fr_64px] gap-2.5 text-[11.5px] text-ink-3"><span>업종</span><span className="text-right">발표</span><span>업종보다 강한 비율</span><span className="text-right">초과 중앙</span></div>
        <FillArea aria-label="업종별 반응"><ul>{d!.groups.map(g => <li key={g.group} className="grid grid-cols-[minmax(0,1fr)_54px_1fr_64px] items-center gap-2.5 border-b py-[7px] text-[12.5px]">
          <span className="truncate">{g.group}</span>
          <span className="text-right font-mono text-ink-3">{formatNumber(g.n)}곳</span>
          <span aria-hidden className="h-1.5 rounded-[3px] bg-chip"><span className="block h-1.5 rounded-[3px] bg-ink-2" style={{ width: `${g.up_ratio ?? 0}%` }} /></span>
          <span className={cn("text-right font-mono tabular-nums", tone(g.median_x1))}>{g.median_x1 == null ? "-" : `${formatPercent(g.median_x1)}p`}</span>
        </li>)}</ul></FillArea>
        {!!d!.pending.length && <div className="flex shrink-0 flex-wrap items-center gap-1.5 overflow-hidden max-h-[26px]">
          <span className="mr-1 text-xs text-ink-3">곧 발표</span>
          {d!.pending.slice(0, 8).map(p => <Badge key={p.corp_code} asChild variant="outline" className="h-[26px] rounded-full px-2.5 font-normal">
            <Link to={`/analyze/${p.stock_code}/summary`}>{p.corp_name}</Link>
          </Badge>)}
        </div>}
      </>
    }}</FillState>
  </MarketCard>
}

/** ⑤ 왼쪽 — 개인 투자 열기(D-231, §4.17). 국면 배지 + 근거 두 줄 → 지표(값 · 5년 백분위 막대 · 백분위). 오류는 이 칸만(§4.28) */
export function RetailCard() {
  const q = useRetailSummary()
  const d = q.data
  return <MarketCard band="local" label="retail.heat" id="retail">
    <BlockHead section title="개인 투자 열기" sub={d?.as_of ? `${md(d.as_of)} 기준` : undefined} link={{ to: "/retail", label: "추이 보기" }}
      info="국장 개인 자금의 과열·냉각을 신용융자·예탁금·회전율·반대매매로 판정합니다. 막대는 과거 5년 백분위. 평일 18:30에 금융투자협회 통계를 받습니다" />
    <FillState data={d} isError={q.isError} error={q.error} onRetry={() => void q.refetch()} message="개인 투자 열기 지표를 불러오지 못했습니다">{() => !d!.regime
      ? <FillNote>아직 수집된 자료가 없습니다. 평일 18:30에 받습니다.</FillNote>
      : <>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <RegimeBadge regime={d!.regime} />
          <span className="min-w-0 text-[12.5px] text-ink-2">{d!.regime.reasons.slice(0, 2).join(" · ")}</span>
        </div>
        <FillArea aria-label="개인 투자 지표"><ul>{d!.metrics.filter(m => m.value != null).map(m => <li key={m.key} className="grid grid-cols-[minmax(0,1fr)_70px_90px_36px] items-center gap-2.5 border-b py-[7px] text-[12.5px]">
          <span className="truncate" title={m.label}>{m.label}</span>
          <span className={cn("text-right font-mono tabular-nums", m.unit === "rate" && tone(m.value))}>{metricValue(m)}</span>
          <span aria-hidden className="h-1.5 rounded-[3px] bg-chip"><span className="block h-1.5 rounded-[3px] bg-down" style={{ width: `${Math.max(2, m.pctile ?? 0)}%` }} /></span>
          <span className="text-right font-mono text-ink-3 tabular-nums">{m.pctile == null ? "-" : Math.round(m.pctile)}</span>
        </li>)}</ul></FillArea>
      </>}</FillState>
  </MarketCard>
}

/** ⑤ 오른쪽 — 수출입 요약(D-140): 수출 총액 · 기여 1위 → 산업별 수출 규모 막대(칸 안 스크롤). 새 달 통계 전에는 'n월 기준' 칩(§4.28 부분) */
export function TradeCard() {
  const q = useTradeHighlights(100)
  const d = q.data
  const month = d?.period ? `${+d.period.slice(5, 7)}월` : ""
  return <MarketCard band="local" label="kr.trade">
    <BlockHead section title="수출입" sub={d?.period ? `${d.period.slice(0, 4)}년 ${month} · 관세청 품목별` : undefined} link={{ to: "/follow/trade", label: "산업 › 수출입" }}
      info="수출 총액 · 증가분 기여 1위 · 산업별 수출 규모. 새 달 통계는 매월 중순에 나옵니다" />
    <FillState data={d} isError={q.isError} error={q.error} onRetry={() => void q.refetch()} message="수출입 통계를 불러오지 못했습니다">{() => {
      if (!d!.period) return <FillNote>수출입 통계가 아직 없습니다. 매일 09:20에 새 통계월을 확인합니다.</FillNote>
      const top = d!.surge[0]
      const groups = d!.groups.slice(0, 12)
      const max = Math.max(...groups.map(g => g.value), 1)
      return <>
        <div className="flex shrink-0 flex-wrap items-baseline gap-x-6 gap-y-1">
          <div>
            <div className="flex items-center gap-1.5 text-xs text-ink-3">수출 총액{tradeIsLagging(d!.period) && <Badge variant="warn">{month} 기준</Badge>}</div>
            <div className="font-display text-[28px] tabular-nums">{formatUsd(d!.total_usd)}</div>
          </div>
          {top && <div className="min-w-0">
            <div className="text-xs text-ink-3">기여 1위</div>
            <div className="text-[13.5px] font-semibold">
              <Link to={`/follow/trade?hs=${encodeURIComponent(top.hs_code)}`} className="hover:underline">{top.item_name}</Link>
              {" · "}전년 대비 <span className={tone(top.yoy)}>{formatPercent(top.yoy == null ? null : top.yoy * 100, 0)}</span>
              {top.contribution != null && <> · 증가분의 {formatRatio(top.contribution * 100).replace(".0%", "%")}</>}
            </div>
          </div>}
        </div>
        <FillArea aria-label="산업별 수출"><ul>{groups.map(g => <li key={g.group_label} className="grid grid-cols-[minmax(0,132px)_1fr_64px_58px] items-center gap-2.5 py-[5px] text-[12.5px]">
          <span className="truncate">{g.group_label}</span>
          <span aria-hidden className="h-1.5 rounded-[3px] bg-chip"><span className="block h-1.5 rounded-[3px] bg-ink-2" style={{ width: `${Math.max(1.5, g.value / max * 100)}%` }} /></span>
          <span className="text-right font-mono tabular-nums">{formatUsd(g.value)}</span>
          <span className="text-right font-mono whitespace-nowrap">{g.surge ? <span className="text-up-ink">급등 {g.surge}</span> : g.plunge ? <span className="text-down-ink">급감 {g.plunge}</span> : <span className="text-ink-3">-</span>}</span>
        </li>)}</ul></FillArea>
      </>
    }}</FillState>
  </MarketCard>
}
