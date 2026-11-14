import { useState, type ReactNode } from "react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { FillArea } from "@/components/shared/Bounded"
import { PagerBar, paged } from "@/components/shared/PagerBar"
import { BlockHead } from "@/components/home/HomeSection"
import { BlockError, tone } from "@/components/home/blockState"
import { FillNote, FillSkeleton, MarketCard } from "@/components/home/MarketFrame"
import { useIsMobile } from "@/hooks/use-mobile"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"

/* 홈 › 한국·미국 시장 두 탭이 같이 쓰는 칸 — ② 거래대금 쏠림 · ③ 거래대금 상위 종목 표(ia-redesign §4.2·4.3) */

export interface FlowCluster { label: string; share_pct: number; median_change: number; has_new: boolean; to?: string; title?: string }

/** 상태 공통 — 데이터 전 뼈대/오류, 뒤에 본문 */
export function FillState({ data, isError, error, onRetry, message, rows, children }: {
  data: unknown; isError: boolean; error?: unknown; onRetry: () => void; message: string; rows?: number; children: () => ReactNode
}) {
  if (data) return <>{children()}</>
  return isError ? <BlockError message={message} error={error} onRetry={onRetry} /> : <FillSkeleton rows={rows} />
}

/** ② 오른쪽 — 거래대금 상위 20종목을 업종으로 묶은 비중과 업종 대표(중앙값) 등락. 요약 한 줄 → 막대 줄(칸 안 스크롤) */
export function FlowCard({ market, clusters, day, n, state, info }: {
  market: "kr" | "us"; clusters: FlowCluster[] | null; day: string | null; n: number
  state: { isError: boolean; error?: unknown; onRetry: () => void }; info: string
}) {
  const top = clusters?.[0]
  return <MarketCard band="summary" label={`${market}.flow`}>
    <BlockHead section title="거래대금 쏠림" info={info} sub={day ? `상위 ${n}종목 · ${day}` : <span aria-hidden className="invisible">상위 20종목 · 00/00</span>} />
    <FillState data={clusters} {...state} message="거래대금 쏠림을 불러오지 못했습니다" rows={10}>{() => !clusters!.length
      ? <FillNote>거래대금 스냅샷이 아직 없습니다.</FillNote>
      : <>
        {top && <p className="shrink-0 text-[13.5px] leading-relaxed">상위 {n}종목 거래대금의 {Math.round(top.share_pct)}%가 {top.label}에 몰렸고 대표 등락은 {formatPercent(top.median_change)}였어요.</p>}
        <FillArea aria-label="업종별 쏠림">
          <ul>{clusters!.map(c => <li key={c.label} className="grid grid-cols-[minmax(0,132px)_1fr_52px_58px] items-center gap-2.5 py-[5px] text-[12.5px]">
            <span className="flex min-w-0 items-center gap-1.5">
              {c.to ? <Link to={c.to} title={c.title} className="truncate hover:underline">{c.label}</Link> : <span className="truncate" title={c.title}>{c.label}</span>}
              {c.has_new && <Badge>신규</Badge>}
            </span>
            <span aria-hidden className="h-1.5 rounded-[3px] bg-chip"><span className="block h-1.5 rounded-[3px] bg-ink-2" style={{ width: `${Math.max(1.5, Math.min(100, c.share_pct))}%` }} /></span>
            <span className="text-right font-mono tabular-nums">{Math.round(c.share_pct)}%</span>
            <span className={cn("text-right font-mono tabular-nums", tone(c.median_change))}>{formatPercent(c.median_change)}</span>
          </li>)}</ul>
        </FillArea>
      </>}</FillState>
  </MarketCard>
}

export interface TurnoverRow {
  key: string; rank: number; name: ReactNode
  /** 한국 = 업종, 미국 = 실적 링크 */
  middle: ReactNode
  change_pct: number | null; value: string
}

/** ③ 왼쪽 — 거래대금 상위 종목 표(10개씩 페이지). 좁은 화면은 종목 · 등락 · 거래대금 세 열 */
export function TurnoverCard({ market, rows, sub, middleLabel, state }: {
  market: "kr" | "us"; rows: TurnoverRow[] | null; sub: ReactNode; middleLabel: string
  state: { isError: boolean; error?: unknown; onRetry: () => void }
}) {
  const [page, setPage] = useState(0)
  const mobile = useIsMobile()
  const pg = paged(rows ?? [], page, 10)
  const th = "h-auto px-2 py-1.5 text-xs font-medium text-ink-3"
  const td = "px-2 py-[7px] text-[13px]"
  return <MarketCard band="stocks" label={`${market}.turnover`}>
    <BlockHead section title="거래대금 상위 종목" sub={sub} link={{ to: "/discover", label: "종목 발견" }} />
    <FillState data={rows} {...state} message="거래대금 상위 종목을 불러오지 못했습니다" rows={10}>{() => !rows!.length
      ? <FillNote>거래대금 스냅샷이 아직 없습니다.</FillNote>
      : <>
        <FillArea aria-label="거래대금 상위 종목 표">
          <Table className="table-fixed tabular-nums">
            <TableHeader><TableRow className="hover:bg-transparent">
              {!mobile && <TableHead className={cn(th, "w-9")}>#</TableHead>}
              <TableHead className={th}>종목</TableHead>
              {!mobile && <TableHead className={cn(th, market === "kr" ? "w-[130px]" : "w-24")}>{middleLabel}</TableHead>}
              <TableHead className={cn(th, "w-[76px] text-right")}>등락</TableHead>
              <TableHead className={cn(th, "w-[76px] text-right")}>거래대금</TableHead>
            </TableRow></TableHeader>
            <TableBody>{pg.rows.map(r => <TableRow key={r.key} className="hover:bg-transparent">
              {!mobile && <TableCell className={cn(td, "font-mono text-ink-3")}>{r.rank}</TableCell>}
              <TableCell className={cn(td, "min-w-0")}><span className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap">{r.name}</span></TableCell>
              {!mobile && <TableCell className={cn(td, "truncate text-ink-2")}>{r.middle}</TableCell>}
              <TableCell className={cn(td, "text-right font-mono", tone(r.change_pct))}>{formatPercent(r.change_pct, 2)}</TableCell>
              <TableCell className={cn(td, "text-right font-mono")}>{r.value}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </FillArea>
        <PagerBar {...pg} onPage={setPage} label="거래대금 상위 종목 페이지" />
      </>}</FillState>
  </MarketCard>
}

/** 링크 이름(시안: 13 · 500) */
export function NameLink({ to, children, mono = false }: { to: string; children: ReactNode; mono?: boolean }) {
  return <Link to={to} className={cn("min-w-0 truncate font-medium hover:underline", mono && "font-mono")}>{children}</Link>
}
