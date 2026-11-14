import { useState } from "react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { FillArea } from "@/components/shared/Bounded"
import { PagerBar, paged } from "@/components/shared/PagerBar"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError } from "@/components/home/blockState"
import { FillNote, FillSkeleton, MarketCard, Seg } from "@/components/home/MarketFrame"
import RightsProTable from "@/components/actions/RightsProTable"
import { pinMine, useActions } from "@/hooks/useActions"
import { useUrlParam } from "@/hooks/useUrlParam"
import { reportTitle } from "@/lib/dossier"
import { formatNumber } from "@/utils/format"
import type { CorporateAction } from "@/types"

const INFO = "시가총액 5,000억 이상 · 최근 30일 · DART 공시 자동 분류. 증자·공개매수·자사주·합병 등 원공시만 보이고 정정 공시는 뺍니다. 내 종목(보유·관심)은 위로 올립니다."
/** 한 페이지 줄 수(시안 Home-KR ④) */
const PER = 6

/**
 * 시장 전체 기업활동 (시총 5,000억+ KOSPI/KOSDAQ) — 홈 › 한국 시장 ④ 오른쪽 `#actions` 칸(D-300, 시안 Home-KR).
 * 옛 /actions는 여기로, /actions?code=X는 그 종목 도시에 개요 맨 아래 기업활동으로 보낸다(§10.6).
 * 원공시만 · 날짜 | 기업 + 유형 · 한 줄 설명(D-306) · 6개씩 페이지. 보기(URL ?acts=)는 전체 | 내 그룹(보유·관심) | 유무증 Pro.
 * 칸 높이는 고정(띠 ④) — 보기·페이지를 바꿔도 칸이 그대로다.
 */
export function ActionsList(_: { variant: "block" }) {
  const { data, isLoading, isError, refetch } = useActions({ kind: "original" })
  const [view, setView] = useUrlParam("acts", "all")
  const [page, setPage] = useState(0)
  const all = data ? pinMine(data.items) : []
  const items = view === "mine" ? all.filter(a => a.my_group) : all
  const pg = paged(items, page, PER)
  const pick = (v: string) => { setPage(0); setView(v) }
  return (
    <MarketCard band="events" label="actions" id="actions">
      <BlockHead section title="기업활동" info={INFO} sub={data ? `원공시 · 최근 30일 ${formatNumber(all.length)}건` : <span aria-hidden className="invisible">원공시 · 최근 30일 00건</span>}
        asOf={data && !data.as_of ? "갱신 기록 없음" : null} stale={!!data && !data.as_of}
        actions={<Seg label="기업활동 보기" value={view} onChange={pick}
          items={[{ key: "all", label: "전체" }, { key: "mine", label: "내 그룹" }, { key: "pro", label: "유무증 Pro" }]} />} />
      {isLoading ? <FillSkeleton rows={PER} label="기업활동 불러오는 중" />
        : isError || !data ? <BlockError message="기업활동을 불러오지 못했습니다" onRetry={() => void refetch()} />
        : view === "pro" ? <FillArea aria-label="유무증 Pro"><RightsProTable /></FillArea>
        : !items.length ? <FillNote>{view === "mine" ? "보유·관심 종목의 기업활동 공시가 없습니다." : data.counts?.correction ? `원공시는 없고 정정 공시 ${data.counts.correction}건이 있습니다.` : "최근 30일 기업활동 공시가 없습니다."}</FillNote>
        : <>
          <FillArea aria-label="기업활동 목록"><ul>{pg.rows.map(a => <ActionRow key={a.id} a={a} />)}</ul></FillArea>
          <PagerBar {...pg} onPage={setPage} label="기업활동 페이지" />
        </>}
    </MarketCard>
  )
}

function ActionRow({ a }: { a: CorporateAction }) {
  const date = `${+a.rcept_dt.slice(4, 6)}/${+a.rcept_dt.slice(6, 8)}`
  const desc = a.description ?? reportTitle(a.report_nm)
  return <li className="grid grid-cols-[40px_minmax(0,1fr)] gap-2.5 border-b py-[9px]">
    <span className="pt-0.5 font-mono text-[11.5px] text-ink-3 tabular-nums">{date}</span>
    <div className="flex min-w-0 flex-col gap-[3px]">
      <div className="flex min-w-0 items-center gap-2">
        {a.stock_code ? <Link to={`/analyze/${a.stock_code}/summary`} className="truncate text-[13.5px] font-medium hover:underline">{a.corp_name}</Link>
          : <span className="truncate text-[13.5px] font-medium">{a.corp_name}</span>}
        <Badge>{a.action_type}</Badge>
        {a.my_group && <Badge variant="outline">{a.my_group}</Badge>}
      </div>
      <a href={a.dart_url} target="_blank" rel="noreferrer" title={reportTitle(a.report_nm)} data-action-desc
        className="truncate text-[12.5px] text-ink-2 hover:underline">{desc}</a>
    </div>
  </li>
}
