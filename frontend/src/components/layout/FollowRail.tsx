import { useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { ChevronDown, ChevronRight, Plus } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { cn } from "@/lib/utils"
import { useWatchlist } from "@/hooks/useWatchlist"
import { useTelegramChannels, useToggleTelegramChannel } from "@/hooks/useTelegram"
import { useBlogSources, useToggleBlogSource } from "@/hooks/useBlogFeed"
import { formatNumber, formatPercent } from "@/utils/format"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import type { WatchlistItem } from "@/types"

/**
 * 팔로우 레일 — 모든 화면에서 동일한 단일 사이드바 (docs/specs/follow-rail.md)
 * 종목·채널·블로그는 같은 프리미티브("내가 팔로우하는 대상"):
 * 행 클릭 = 도시에 이동, hover = 토글 노출, [+] = 추가.
 */

function gapColor(gap: number | null): string {
  if (gap === null) return "text-muted-foreground"
  if (gap >= 30) return "text-emerald-600"
  if (gap >= 10) return "text-emerald-500"
  if (gap >= 0) return "text-emerald-400"
  if (gap >= -10) return "text-rose-400"
  return "text-rose-600"
}

function useSourcesHealth() {
  return useQuery({
    queryKey: ["spine", "sources", "health"],
    queryFn: async () => (await api.get("/api/spine/sources/health")).data as {
      items: { kind: string; key: string; docs_7d: number; warning: boolean }[]
    },
    staleTime: 5 * 60_000,
  })
}

/* ---------- 공통 조각 ---------- */

function Section({ title, count, onAdd, addLabel, children }: {
  title: string
  count: number
  onAdd: () => void
  addLabel: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="py-1">
      <div className="flex items-center gap-1 px-2.5 py-1.5">
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1 text-xs font-semibold text-secondary-foreground hover:text-foreground min-w-0"
        >
          {open ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
          {title}
          <span className="font-normal text-muted-foreground tabular-nums">{count}</span>
        </button>
        <Button variant="ghost" size="icon-xs" onClick={onAdd} title={addLabel}
          className="ml-auto text-muted-foreground hover:text-foreground">
          <Plus className="h-3 w-3" />
        </Button>
      </div>
      {open && children}
    </div>
  )
}

function Row({ active, warning, onClick, name, sub, right }: {
  active: boolean
  warning?: boolean
  onClick: () => void
  name: React.ReactNode
  sub: React.ReactNode
  right?: React.ReactNode
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "group flex items-center gap-1 px-3 py-2 cursor-pointer border-l-[3px] transition-colors",
        active ? "bg-accent border-l-primary" : "border-l-transparent hover:bg-muted/50"
      )}
    >
      <div className="min-w-0 flex-1">
        <div className={cn(
          "text-[13px] truncate flex items-center gap-1",
          active ? "font-semibold text-primary" : "text-foreground"
        )}>
          {warning && (
            <span className="h-1.5 w-1.5 rounded-full bg-destructive shrink-0" title="7일간 유입 없음" />
          )}
          {name}
        </div>
        <div className="text-[11px] text-muted-foreground truncate mt-0.5">{sub}</div>
      </div>
      {right}
    </div>
  )
}

function SourceToggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onToggle() }}
      className={cn(
        "shrink-0 w-[18px] h-[18px] rounded-full border-2 flex items-center justify-center transition-all",
        "opacity-0 group-hover:opacity-100",
        active ? "border-primary bg-primary text-primary-foreground" : "border-muted-foreground/30 opacity-40 group-hover:opacity-100"
      )}
      title={active ? "수집 중지" : "수집 재개"}
    >
      {active && <span className="text-[9px] leading-none">✓</span>}
    </button>
  )
}

function AddForm({ placeholder, onSubmit, pending }: {
  placeholder: string
  onSubmit: (value: string) => void
  pending: boolean
}) {
  return (
    <form
      className="px-3 pb-2 flex gap-1"
      onSubmit={(e) => {
        e.preventDefault()
        const v = new FormData(e.currentTarget).get("v")?.toString().trim()
        if (v) {
          onSubmit(v)
          ;(e.target as HTMLFormElement).reset()
        }
      }}
    >
      <input name="v" placeholder={placeholder} disabled={pending} autoFocus
        className="min-w-0 flex-1 h-7 rounded-md border bg-background px-2 text-[11px] outline-none focus:ring-1 focus:ring-ring" />
      <button type="submit" disabled={pending}
        className="shrink-0 h-7 px-2 rounded-md bg-primary text-primary-foreground text-[11px] disabled:opacity-50">
        {pending ? "…" : "추가"}
      </button>
    </form>
  )
}

function EmptyRow({ message }: { message: string }) {
  return <p className="px-3 py-2 text-[11px] text-muted-foreground">{message}</p>
}

/* ---------- 섹션들 ---------- */

function StockSection({ currentStockCode }: { currentStockCode: string | null }) {
  const navigate = useNavigate()
  const { data: items = [], isLoading } = useWatchlist()
  if (isLoading) return <div className="px-3 py-2"><Skeleton className="h-4 w-full" /></div>

  return (
    <Section title="종목" count={items.length} onAdd={() => navigate("/research/watchlist")} addLabel="워치리스트 관리">
      {items.length === 0 && <EmptyRow message="아직 없음 — +로 추가" />}
      {items.map((item: WatchlistItem) => (
        <Row
          key={item.id}
          active={item.stock_code === currentStockCode}
          onClick={() => navigate(`/analyze/${item.stock_code}/summary`)}
          name={item.corp_name}
          sub={
            <span className="flex items-center gap-1.5">
              <span className="text-amber-400 text-[10px] tracking-tighter">
                {"★".repeat(item.conviction)}{"☆".repeat(5 - item.conviction)}
              </span>
              <span>{item.latest_close != null ? formatNumber(item.latest_close) : "-"}</span>
              {item.gap_pct != null && (
                <span className={cn("font-medium", gapColor(item.gap_pct))}>{formatPercent(item.gap_pct)}</span>
              )}
            </span>
          }
        />
      ))}
    </Section>
  )
}

function useActiveSource(): { kind: string; key: string } | null {
  const { pathname } = useLocation()
  const [searchParams] = useSearchParams()
  if (pathname !== "/source") return null
  const kind = searchParams.get("kind")
  const key = searchParams.get("key")
  return kind && key ? { kind, key } : null
}

function ChannelSection() {
  const navigate = useNavigate()
  const activeSource = useActiveSource()
  const { data: channels = [], isLoading } = useTelegramChannels()
  const { data: health } = useSourcesHealth()
  const healthMap = new Map((health?.items ?? []).filter((i) => i.kind === "telegram").map((i) => [i.key, i]))
  const toggle = useToggleTelegramChannel()
  const [showForm, setShowForm] = useState(false)
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async (channel: string) =>
      (await api.post("/api/spine/sources/telegram", { channel })).data as { channel: string; preview_messages: number },
    onSuccess: (d) => {
      toast.success(`@${d.channel} 등록 — 백그라운드 수집 시작 (프리뷰 ${d.preview_messages}건)`)
      qc.invalidateQueries({ queryKey: ["telegram-channels"] })
      setShowForm(false)
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? "채널 등록 실패")
    },
  })
  if (isLoading) return <div className="px-3 py-2"><Skeleton className="h-4 w-full" /></div>

  return (
    <Section title="채널" count={channels.length} onAdd={() => setShowForm(!showForm)} addLabel="채널 추가">
      {showForm && (
        <AddForm placeholder="t.me/채널명 또는 @채널명" onSubmit={(v) => add.mutate(v)} pending={add.isPending} />
      )}
      {channels.length === 0 && !showForm && <EmptyRow message="아직 없음 — +로 추가" />}
      {channels.map((ch) => {
        const active = ch.is_active === 1
        const h = healthMap.get(ch.channel_name)
        return (
          <Row
            key={ch.id}
            active={activeSource?.kind === "telegram" && activeSource.key === ch.channel_name}
            warning={h?.warning}
            onClick={() => navigate(`/source?kind=telegram&key=${encodeURIComponent(ch.channel_name)}`)}
            name={<span className={cn(!active && "opacity-50")}>{ch.display_name ?? ch.channel_name}</span>}
            sub={`7일 ${h?.docs_7d ?? "-"}건`}
            right={<SourceToggle active={active} onToggle={() => toggle.mutate({ id: ch.id, is_active: !active })} />}
          />
        )
      })}
    </Section>
  )
}

function BlogSection() {
  const navigate = useNavigate()
  const activeSource = useActiveSource()
  const { data: sources = [], isLoading } = useBlogSources()
  const { data: health } = useSourcesHealth()
  const healthMap = new Map((health?.items ?? []).filter((i) => i.kind === "blog").map((i) => [i.key, i]))
  const toggle = useToggleBlogSource()
  const [showForm, setShowForm] = useState(false)
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async (url: string) =>
      (await api.post("/api/spine/sources/blog", { url })).data as { url: string; blog_name: string | null },
    onSuccess: (d) => {
      toast.success(`'${d.blog_name || d.url}' 등록 — 백그라운드 수집 시작`)
      qc.invalidateQueries({ queryKey: ["blog-sources"] })
      setShowForm(false)
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? "블로그 등록 실패")
    },
  })
  if (isLoading) return <div className="px-3 py-2"><Skeleton className="h-4 w-full" /></div>

  return (
    <Section title="블로그" count={sources.length} onAdd={() => setShowForm(!showForm)} addLabel="블로그 추가">
      {showForm && (
        <AddForm placeholder="블로그 URL (네이버/티스토리/RSS)" onSubmit={(v) => add.mutate(v)} pending={add.isPending} />
      )}
      {sources.length === 0 && !showForm && <EmptyRow message="아직 없음 — +로 추가" />}
      {sources.map((src) => {
        const active = src.is_active === 1
        const h = healthMap.get(src.url)
        return (
          <Row
            key={src.id}
            active={activeSource?.kind === "blog" && activeSource.key === src.url}
            warning={h?.warning}
            onClick={() => navigate(`/source?kind=blog&key=${encodeURIComponent(src.url)}`)}
            name={<span className={cn(!active && "opacity-50")}>{src.blog_name || src.url}</span>}
            sub={`${src.author ?? src.platform} · 7일 ${h?.docs_7d ?? "-"}건`}
            right={<SourceToggle active={active} onToggle={() => toggle.mutate({ id: src.id, is_active: !active })} />}
          />
        )
      })}
    </Section>
  )
}

/* ---------- 레일 ---------- */

export default function FollowRail({ currentStockCode }: { currentStockCode: string | null }) {
  const [collapsed, setCollapsed] = useState(false)

  if (collapsed) {
    return (
      <Button
        variant="ghost"
        onClick={() => setCollapsed(false)}
        className="fixed right-0 top-[120px] w-8 h-20 bg-card border border-r-0 rounded-l-lg flex items-center justify-center cursor-pointer shadow-sm text-xs text-muted-foreground"
        style={{ writingMode: "vertical-rl" }}
      >
        팔로우
      </Button>
    )
  }

  return (
    <aside className="w-[220px] shrink-0 bg-card border-l sticky top-[110px] h-[calc(100vh-110px)] py-2">
      <ScrollArea className="h-full">
        <div className="flex items-center justify-between px-2.5 pt-1 pb-0.5">
          <h3 className="text-[11px] font-semibold text-muted-foreground tracking-wide">팔로우</h3>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={() => setCollapsed(true)}
            className="text-muted-foreground hover:text-foreground text-sm leading-none"
          >
            ✕
          </Button>
        </div>
        <div className="divide-y">
          <StockSection currentStockCode={currentStockCode} />
          <ChannelSection />
          <BlogSection />
        </div>
      </ScrollArea>
    </aside>
  )
}
