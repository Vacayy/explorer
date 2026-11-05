import { Fragment, useMemo, useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { PageLayout } from "@/components/shared/PageLayout"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { HorizontalCarousel } from "@/components/shared/HorizontalCarousel"
import { HomeSection } from "@/components/home/HomeSection"
import { BlockError, RowsSkeleton, tone } from "@/components/home/blockState"
import { TrackerBody } from "@/components/widgets/tracker"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAddMember, useDefaultWatchGroup, useRemoveMember, useSetTracked } from "@/hooks/useGroups"
import { usePortfolio } from "@/hooks/usePortfolio"
import { useStockSearch } from "@/hooks/useStockSearch"
import { useTracker, useTrackerStatus } from "@/hooks/useTracker"
import { useSeason } from "@/hooks/useTranscripts"
import { useIsMobile } from "@/hooks/use-mobile"
import { localToday } from "@/lib/seasonPhase"
import { earningsBadge, featured as featuredOf, leadSignal, marketLabel, signalDetail, splitRows, trackedNotice } from "@/lib/myStocks"
import { cn } from "@/lib/utils"
import { formatKrw, formatNumber, formatPercent, formatStockPrice } from "@/utils/format"
import type { SeasonOverview, StockGroupDetail, StockGroupMember, TrackerCondition } from "@/types"

/**
 * 홈 › 내 종목 (시안 Home-Stocks·Mobile-Stocks, ia-redesign §4.4·§4.20·§4.28) — 기본 관심 묶음 하나를 본다.
 * 머리 줄(보기 전환·종목 추가) → 특징주(오늘 신호) → 조건 충족 알림 줄(새로 충족된 날만) → 목록(추적 행 먼저, 펼치면 조건·신호·수급).
 * 추적 = 관심 종목의 '추적' 표시(알림 대상, 국내 종목·미국 티커). 보기(view)와 펼친 행(open)은 URL이 정한다.
 */
type View = "all" | "tracked" | "held"
const VIEWS = [{ value: "all", label: "전체" }, { value: "tracked", label: "추적" }, { value: "held", label: "보유" }]
/** 더 보기 전 비추적 행 수 — 데스크톱 10 · 모바일 6 (시안 Home-Stocks·Mobile-Stocks, D-301) */
const UNTRACKED_LIMIT = { desktop: 10, mobile: 6 }
const ROLE: Record<TrackerCondition["role"], string> = { entry: "진입", exit: "손절·청산", check: "확인" }
const dossierPath = (code: string, market?: string | null) => (market === "us" ? `/us/${code}` : `/analyze/${code}/summary`)
const eok = (v: number) => `${v > 0 ? "+" : ""}${formatKrw(v * 1e8)}`
const mmdd = (iso?: string | null) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}` : "")

export default function HomeStocksPage() {
  const group = useDefaultWatchGroup()
  const [params, setParams] = useSearchParams()
  const view = (["tracked", "held"].includes(params.get("view") ?? "") ? params.get("view") : "all") as View
  const open = params.get("open")
  const setParam = (key: string, value: string | null) => setParams(prev => {
    const next = new URLSearchParams(prev)
    if (value) next.set(key, value); else next.delete(key)
    return next
  }, { replace: true })
  const [adding, setAdding] = useState(false)

  const members = group.data?.members ?? []
  const trackedCodes = members.filter(m => m.tracked).map(m => m.stock_code)
  const status = useTrackerStatus(trackedCodes.length > 0)
  const season = useSeason()
  const portfolio = usePortfolio()

  const header = (stats: ReactNode) => <Header view={view} onView={v => setParam("view", v === "all" ? null : v)} onAdd={() => setAdding(true)} stats={stats} />
  const addDialog = group.data && <AddDialog detail={group.data} open={adding} onOpenChange={setAdding} />

  if (group.isPending) return <PageLayout mode="document">
    <Card className="gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none">
      {header(<Skeleton className="h-4 w-64" />)}
      <div className="p-4"><RowsSkeleton rows={6} /></div>
    </Card>
  </PageLayout>
  if (group.isError || !group.data) return <PageLayout mode="document">
    <Card className="gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none">
      {header(null)}
      <div className="p-4"><BlockError message="관심 종목을 불러오지 못했습니다" error={group.error} onRetry={() => void group.refetch()} /></div>
    </Card>
  </PageLayout>

  const detail = group.data
  // 충족 수·알림 줄은 가벼운 요약(/tracker/status)에서 — 지금 관심 목록에서 추적 중인 종목만 센다
  const statusItems = (status.data?.items ?? []).filter(i => trackedCodes.includes(i.code))
  const metCount = statusItems.reduce((n, i) => n + i.met, 0)
  const up = members.filter(m => (m.change_pct ?? 0) > 0).length
  const down = members.filter(m => (m.change_pct ?? 0) < 0).length
  const stats = <>관심 {formatNumber(members.length)}종목 · 추적 {formatNumber(trackedCodes.length)}{status.data && <>(충족 {formatNumber(metCount)})</>} · 상승 {formatNumber(up)} · 하락 {formatNumber(down)}
    <span className="hidden md:inline"> · 오늘 켜진 감시 신호 {formatNumber(detail.today_signals)}개</span></>

  if (!members.length) return <PageLayout mode="document">
    <Card className="gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none" data-stocks-state="empty">
      {header(null)}
      <div className="space-y-3 p-4 text-sm">
        <p className="text-muted-foreground">관심 종목이 없습니다. 국내 종목 이름이나 미국 티커로 추가할 수 있어요.</p>
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}><Plus className="size-3.5" />종목 추가</Button>
      </div>
    </Card>
    {addDialog}
  </PageLayout>

  const held = new Set((portfolio.data?.holdings ?? []).map(h => h.code))
  const visible = view === "tracked" ? members.filter(m => m.tracked) : view === "held" ? members.filter(m => held.has(m.stock_code)) : members
  const alerts = statusItems.flatMap(i => i.conditions.filter(c => c.newly_met).map(c => ({ code: i.code, name: i.name, label: c.label })))

  return <PageLayout mode="document">
    <div className="flex flex-col gap-4">
      <Card className="gap-0 overflow-hidden rounded-[var(--radius-card)] py-0 shadow-none" data-stocks-state="ideal">
        {header(stats)}
        <div className="space-y-4 p-4">
          {view === "all" && <Featured detail={detail} />}
          {view !== "held" && alerts.length > 0 && <AlertLine alerts={alerts} onOpen={code => setParam("open", code)} />}
          {view === "held" && portfolio.isPending ? <RowsSkeleton rows={3} head={false} />
            : visible.length === 0 ? <p className="py-4 text-sm text-muted-foreground">{view === "held" ? "관심 종목 중 보유 종목이 없습니다." : "추적 중인 종목이 없습니다. 목록에서 '추적'을 켜면 조건 충족·새 신호를 알려 드려요."}</p>
            : <StockList detail={detail} members={visible} limitUntracked={view === "all"} open={open} onOpen={code => setParam("open", code === open ? null : code)}
              season={season.data} />}
        </div>
      </Card>
      {view === "all" && <HomeSection widget="watch.digests" w={12} h={4} />}
      {view === "held" && <div className="surface-grid grid md:grid-cols-2 lg:grid-cols-3">
        <HomeSection widget="portfolio.today" w={4} h={4} />
        <HomeSection widget="portfolio.events" w={4} h={4} />
        <HomeSection widget="portfolio.flow" w={4} h={4} />
      </div>}
    </div>
    {addDialog}
  </PageLayout>
}

function Header({ view, onView, onAdd, stats }: { view: View; onView: (v: string) => void; onAdd: () => void; stats: ReactNode }) {
  return <header className="flex flex-wrap items-end justify-between gap-3 border-b bg-down/5 px-4 py-4">
    <div className="min-w-0">
      <h1 className="text-page font-semibold">내 종목</h1>
      {stats && <div className="mt-1 text-caption text-muted-foreground">{stats}</div>}
    </div>
    <div className="flex w-full items-center justify-between gap-2 md:w-auto">
      <SegmentTabs tabs={VIEWS} value={view} onChange={onView} />
      <Button variant="outline" size="sm" className="rounded-full" onClick={onAdd}><Plus className="size-3.5" />종목 추가</Button>
    </div>
  </header>
}

/* ── 특징주: 오늘 신호가 들어온 관심 종목 4장(모바일은 가로 스크롤) ── */
function Featured({ detail }: { detail: StockGroupDetail }) {
  const mobile = useIsMobile()
  const items = featuredOf(detail.members)
  const all = `/follow/stocks?group=${detail.id}`
  if (!items.length) return <p className="text-sm text-muted-foreground" data-stocks-featured="none">오늘 들어온 신호 없음</p>
  const cards = items.slice(0, mobile ? 8 : 4).map(m => <FeaturedCard key={m.stock_code} m={m} className={mobile ? "w-[15rem] shrink-0 snap-start" : undefined} />)
  return <section aria-labelledby="featured-title" className="space-y-2" data-stocks-featured="cards">
    <div className="flex items-baseline justify-between gap-2">
      <h2 id="featured-title" className="text-sm font-semibold">특징주 <span className="ml-1 text-caption font-normal text-muted-foreground">{mobile ? "신호" : "오늘 신호 들어온 관심 종목"} {formatNumber(items.length)}</span></h2>
      <Link to={all} className="text-caption text-muted-foreground hover:text-foreground">{mobile ? "모두" : `신호 ${formatNumber(detail.today_signals)}개 모두 보기`} ›</Link>
    </div>
    {mobile ? <HorizontalCarousel label="특징주">{cards}</HorizontalCarousel> : <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">{cards}</div>}
  </section>
}

function FeaturedCard({ m, className }: { m: StockGroupMember; className?: string }) {
  const s = leadSignal(m)
  const line = s ? signalDetail(s, m.market) : null
  return <Link to={dossierPath(m.stock_code, m.market)} className={cn("block space-y-1.5 border bg-card p-3 transition-colors hover:bg-muted/40", className)}>
    <p className="flex items-baseline gap-1.5">
      <span className="truncate font-semibold">{m.name}</span>
      <span className="shrink-0 text-[11px] text-muted-foreground">{marketLabel(m.market)}</span>
      {s?.signal_date && <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground">{mmdd(s.signal_date)}{m.market === "us" ? " 신호" : ""}</span>}
    </p>
    <p className="tabular-nums"><span>{formatStockPrice(m.close, m.market)}</span> <span className={tone(m.change_pct)}>{formatPercent(m.change_pct)}</span></p>
    {s && <Badge variant="outline" className="border-transparent bg-up/10 font-normal text-up">{s.label}</Badge>}
    {line && <p className="truncate text-caption text-muted-foreground">{line}</p>}
  </Link>
}

function AlertLine({ alerts, onOpen }: { alerts: { code: string; name: string; label: string }[]; onOpen: (code: string) => void }) {
  const first = alerts[0]
  return <button type="button" onClick={() => onOpen(first.code)} data-stocks-alert
    className="flex w-full items-center gap-2 border px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted/40">
    <Badge variant="outline" className="shrink-0 border-transparent bg-up/10 font-normal text-up">조건 충족</Badge>
    <span className="min-w-0 flex-1 truncate"><b>{first.name}</b> — {first.label}{alerts.length > 1 ? ` 외 ${formatNumber(alerts.length - 1)}건` : ""}</span>
    <span className="shrink-0 text-caption text-muted-foreground"><span className="hidden md:inline">추적 상세 </span>›</span>
  </button>
}

/* ── 목록 ── */
interface ListProps {
  detail: StockGroupDetail
  members: StockGroupMember[]
  limitUntracked: boolean
  open: string | null
  onOpen: (code: string) => void
  season?: SeasonOverview
}

function StockList({ detail, members, limitUntracked, open, onOpen, season }: ListProps) {
  const mobile = useIsMobile()
  const [more, setMore] = useState(false)
  const [confirm, setConfirm] = useState<StockGroupMember | null>(null)
  const [editing, setEditing] = useState<StockGroupMember | null>(null)
  const setTracked = useSetTracked(detail.id)
  const remove = useRemoveMember(detail.id)
  const add = useAddMember()
  const today = localToday()
  const { tracked, untracked, hidden } = useMemo(() => splitRows(members, limitUntracked && !more ? UNTRACKED_LIMIT[mobile ? "mobile" : "desktop"] : Number.MAX_SAFE_INTEGER), [members, limitUntracked, more, mobile])

  const toggle = (m: StockGroupMember, on: boolean) => setTracked.mutateAsync({ stockCode: m.stock_code, tracked: on })
    .then(state => toast.success(state.tracked ? `${m.name} 추적을 켰습니다. ${trackedNotice(m.market)}` : `${m.name} 추적을 껐습니다.`))
    .catch(error => toast.error(error instanceof Error ? error.message : "추적을 바꾸지 못했습니다."))
  const doRemove = (m: StockGroupMember) => remove.mutateAsync(m.stock_code).then(() => toast.success(`${m.name} — 관심 종목에서 뺐습니다.`, {
    action: { label: "되돌리기", onClick: () => void undo(m) },
  })).catch(error => toast.error(error instanceof Error ? error.message : "빼지 못했습니다."))
  const undo = async (m: StockGroupMember) => {
    try {
      await add.mutateAsync({ groupId: detail.id, stock_code: m.stock_code, ...(m.conviction ? { conviction: m.conviction } : {}) })
      if (m.tracked) await setTracked.mutateAsync({ stockCode: m.stock_code, tracked: true })
    } catch (error) { toast.error(error instanceof Error ? error.message : "되돌리지 못했습니다.") }
  }
  /** 논지·목표가·종목별 감시 조건이 있으면 확인 창, 없으면 바로 빼고 '되돌리기' */
  const askRemove = (m: StockGroupMember) => (m.thesis || m.target_price || (detail.rules.members[m.stock_code]?.length ?? 0) > 0) ? setConfirm(m) : void doRemove(m)

  const row = (m: StockGroupMember) => {
    const badge = m.market === "us" ? earningsBadge(m.stock_code, season, today) : null
    const props = { m, badge, open: open === m.stock_code, onOpen, onToggle: toggle, onRemove: askRemove, busy: setTracked.isPending }
    const panel = open === m.stock_code && m.tracked ? <DetailPanel code={m.stock_code} market={m.market} onEdit={() => setEditing(m)} /> : null
    return mobile ? <MobileRow key={m.stock_code} {...props} panel={panel} /> : <DesktopRow key={m.stock_code} {...props} panel={panel} />
  }
  const rows = [...tracked, ...untracked].map(row)

  return <>
    {mobile
      ? <div data-stocks-list>
        <div className="flex justify-between border-b pb-1.5 text-caption text-muted-foreground"><span>관심 종목</span><span>추적</span></div>
        <ul>{rows}</ul>
      </div>
      : <Table aria-label="관심 종목" data-stocks-list>
        <TableHeader><TableRow>
          <TableHead>종목</TableHead><TableHead className="text-right">현재가</TableHead><TableHead className="text-right">등락</TableHead>
          <TableHead>오늘 신호</TableHead><TableHead className="w-16 text-center">추적</TableHead><TableHead className="w-10"><span className="sr-only">빼기</span></TableHead>
        </TableRow></TableHeader>
        <TableBody>{rows}</TableBody>
      </Table>}
    {hidden > 0 && <Button variant="ghost" size="sm" className={cn("text-muted-foreground", mobile && "w-full")} onClick={() => setMore(true)}>{formatNumber(hidden)}종목 더 보기 ›</Button>}

    <AlertDialog open={!!confirm} onOpenChange={v => { if (!v) setConfirm(null) }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{confirm?.name}을(를) 관심 종목에서 뺄까요?</AlertDialogTitle>
          <AlertDialogDescription>적어 둔 {[confirm?.thesis && "논지", confirm?.target_price && "목표가", confirm && (detail.rules.members[confirm.stock_code]?.length ?? 0) > 0 && "종목별 감시 조건"].filter(Boolean).join("·")}도 함께 지워집니다.</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>취소</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => { if (confirm) void doRemove(confirm); setConfirm(null) }}>빼기</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <Sheet open={!!editing} onOpenChange={v => { if (!v) setEditing(null) }}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-2xl">
        <SheetHeader className="border-b"><SheetTitle>{editing?.name} 추적 상세</SheetTitle><SheetDescription className="sr-only">원칙 조건 편집·차트·기술적 신호·수급·이슈</SheetDescription></SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto">{editing && <TrackerBody w={12} h={8} params={{ code: editing.stock_code }} />}</div>
      </SheetContent>
    </Sheet>
  </>
}

interface RowProps {
  m: StockGroupMember
  badge: ReturnType<typeof earningsBadge>
  open: boolean
  onOpen: (code: string) => void
  onToggle: (m: StockGroupMember, on: boolean) => void
  onRemove: (m: StockGroupMember) => void
  busy: boolean
  panel: ReactNode
}

function NameCell({ m, badge, open, onOpen }: Pick<RowProps, "m" | "badge" | "open" | "onOpen">) {
  const name = m.tracked
    ? <button type="button" aria-expanded={open} onClick={() => onOpen(m.stock_code)} className="inline-flex min-w-0 items-center gap-1 font-semibold hover:underline">
      {open ? <ChevronDown className="size-3.5 shrink-0" /> : <ChevronRight className="size-3.5 shrink-0" />}<span className="truncate">{m.name}</span>
    </button>
    : <Link to={dossierPath(m.stock_code, m.market)} className="truncate font-semibold hover:underline">{m.name}</Link>
  return <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">
    {name}
    {m.market === "us" ? <Badge variant="outline" className="h-5 px-1.5 text-[11px] font-normal">미국</Badge> : <span className="text-[11px] text-muted-foreground">{marketLabel(m.market)}</span>}
    {badge && (badge.to
      ? <Link to={badge.to} className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">{badge.label} ›</Link>
      : <span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{badge.label}</span>)}
  </span>
}

function DesktopRow({ m, badge, open, onOpen, onToggle, onRemove, busy, panel }: RowProps) {
  const s = leadSignal(m)
  return <Fragment>
    <TableRow data-tracked={m.tracked ? "1" : "0"} data-code={m.stock_code} className={cn(open && "border-b-0")}>
      <TableCell className="max-w-[28rem]"><NameCell m={m} badge={badge} open={open} onOpen={onOpen} /></TableCell>
      <TableCell className="text-right tabular-nums">{formatStockPrice(m.close, m.market)}</TableCell>
      <TableCell className={cn("text-right tabular-nums", tone(m.change_pct))}>{formatPercent(m.change_pct)}</TableCell>
      <TableCell>{s ? <Badge variant="outline" className="border-transparent bg-up/10 font-normal text-up">{s.label}</Badge> : <span className="text-muted-foreground">-</span>}</TableCell>
      <TableCell className="text-center"><Switch checked={m.tracked === 1} disabled={busy} aria-label={`${m.name} 추적`} onCheckedChange={v => onToggle(m, v)} /></TableCell>
      <TableCell><Button variant="ghost" size="icon-xs" aria-label={`${m.name} 빼기`} onClick={() => onRemove(m)}><X className="size-3.5" /></Button></TableCell>
    </TableRow>
    {panel && <TableRow className="hover:bg-transparent"><TableCell colSpan={6} className="whitespace-normal p-0 pb-2">{panel}</TableCell></TableRow>}
  </Fragment>
}

function MobileRow({ m, badge, open, onOpen, onToggle, busy, panel }: RowProps) {
  const s = leadSignal(m)
  return <li data-tracked={m.tracked ? "1" : "0"} data-code={m.stock_code} className="border-b py-3">
    <div className="flex items-center gap-2">
      <div className="min-w-0 flex-1">
        <NameCell m={m} badge={badge} open={open} onOpen={onOpen} />
        {s && <p className="mt-0.5 truncate text-caption text-up">{s.label}</p>}
      </div>
      <div className="shrink-0 text-right tabular-nums">
        <p>{formatStockPrice(m.close, m.market)}</p>
        <p className={tone(m.change_pct)}>{formatPercent(m.change_pct)}</p>
      </div>
      <Switch checked={m.tracked === 1} disabled={busy} aria-label={`${m.name} 추적`} onCheckedChange={v => onToggle(m, v)} />
    </div>
    {panel && <div className="mt-2">{panel}</div>}
  </li>
}

/* ── 추적 행 펼침: 원칙 조건 상태 · 기술적 신호 · 5일 수급 ── */
function DetailPanel({ code, market, onEdit }: { code: string; market: string | null; onEdit: () => void }) {
  const q = useTracker(code)
  if (q.isPending) return <div className="border p-3"><RowsSkeleton rows={3} head={false} /></div>
  if (q.isError || !q.data) return <BlockError message="추적 상세를 불러오지 못했습니다" error={q.error} onRetry={() => void q.refetch()} />
  const d = q.data
  const sigs = d.technicals.signals ?? []
  return <div className="space-y-3 border bg-muted/20 p-3 text-sm" data-stocks-detail={code}>
    <div className="grid gap-3 md:grid-cols-2">
      {d.conditions.length
        ? <ul className="space-y-1.5">{d.conditions.map(c => <li key={c.id} className="flex items-start gap-2">
          <StatusBadge c={c} /><span className="min-w-0"><span className="text-muted-foreground">{ROLE[c.role]}</span> {c.label}</span>
        </li>)}</ul>
        : <p><span className="text-muted-foreground">걸어 둔 조건 없음 · </span><button type="button" onClick={onEdit} className="hover:underline">조건 추가 ›</button></p>}
      {sigs.length > 0 && <div className="flex flex-wrap content-start gap-1.5">{sigs.slice(0, 4).map(s => <Badge key={`${s.id}${s.date}`} variant="outline" className="font-normal">{s.label}</Badge>)}</div>}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 text-caption">
      {d.flows
        ? <span className="tabular-nums"><span className="text-muted-foreground">5일 외국인 </span><span className={tone(d.flows.foreign_5d)}>{eok(d.flows.foreign_5d)}</span>
          <span className="text-muted-foreground"> · 기관 </span><span className={tone(d.flows.inst_5d)}>{eok(d.flows.inst_5d)}</span></span>
        : market === "us"
          ? <span className="tabular-nums text-muted-foreground">{mmdd(d.last_close_date)} 미국 종가 기준{d.technicals.off_52w_high != null ? ` · 52주 고점 대비 ${formatPercent(d.technicals.off_52w_high)}` : ""}</span>
          : <span className="text-muted-foreground">수급은 다음 수집 때 채워집니다</span>}
      <span><button type="button" onClick={onEdit} className="hover:underline">조건 편집</button><span className="text-muted-foreground"> · </span>
        <Link to={dossierPath(code, market)} className="hover:underline">종목 페이지 ›</Link></span>
    </div>
  </div>
}

function StatusBadge({ c }: { c: TrackerCondition }) {
  const [label, cls] = c.status === "met" ? ["충족", "bg-up/10 text-up"] : c.status === "pending" ? ["확인 대기", "bg-muted text-foreground"] : c.status === "not_met" ? ["미충족", "bg-muted text-muted-foreground"] : ["판정 불가", "bg-muted text-muted-foreground"]
  return <Badge variant="outline" className={cn("shrink-0 border-transparent font-normal", cls)}>{label}</Badge>
}

/* ── 종목 추가: 국내 종목 이름·코드 또는 미국 티커 ── */
const TICKER = /^[A-Za-z][A-Za-z0-9.-]{0,9}$/

function AddDialog({ detail, open, onOpenChange }: { detail: StockGroupDetail; open: boolean; onOpenChange: (v: boolean) => void }) {
  const [q, setQ] = useState("")
  const search = useStockSearch(q.trim())
  const add = useAddMember()
  const have = new Set(detail.members.map(m => m.stock_code))
  const ticker = q.trim().toUpperCase()
  const offerTicker = TICKER.test(q.trim()) && !have.has(ticker) && !(search.data?.us ?? []).some(u => u.ticker === ticker)
  const pick = (code: string, name: string) => add.mutateAsync({ groupId: detail.id, stock_code: code })
    .then(() => { toast.success(`${name} — 관심 종목에 넣었습니다.`); setQ(""); onOpenChange(false) })
    .catch(error => toast.error(error instanceof Error ? error.message : "종목을 넣지 못했습니다."))
  const item = (code: string, name: string, sub: string) => <CommandItem key={code} value={code} disabled={have.has(code) || add.isPending} onSelect={() => void pick(code, name)}>
    <span className="min-w-0 flex-1 truncate">{name}</span><span className="text-caption text-muted-foreground">{have.has(code) ? "이미 있음" : sub}</span>
  </CommandItem>
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-md">
      <DialogHeader className="sr-only"><DialogTitle>종목 추가</DialogTitle><DialogDescription>국내 종목 이름·코드 또는 미국 티커</DialogDescription></DialogHeader>
      <Command shouldFilter={false}>
        <CommandInput value={q} onValueChange={setQ} placeholder="종목 이름·코드 또는 미국 티커" />
        <CommandList>
          {q.trim() && !search.isPending && !offerTicker && <CommandEmpty>일치하는 종목이 없습니다.</CommandEmpty>}
          {!!search.data?.companies.length && <CommandGroup heading="국내">{search.data.companies.slice(0, 8).map(c => item(c.stock_code, c.name, `${c.stock_code} · ${c.market ?? ""}`))}</CommandGroup>}
          {(!!search.data?.us.length || offerTicker) && <CommandGroup heading="미국">
            {(search.data?.us ?? []).map(u => item(u.ticker, u.name, u.ticker))}
            {offerTicker && item(ticker, ticker, "티커로 추가")}
          </CommandGroup>}
        </CommandList>
      </Command>
    </DialogContent>
  </Dialog>
}
