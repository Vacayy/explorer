import { useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { ChevronDown, Plus } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { cn } from "@/lib/utils"
import { useWatchlist } from "@/hooks/useWatchlist"
import { useTelegramChannels, useToggleTelegramChannel } from "@/hooks/useTelegram"
import { useBlogSources, useToggleBlogSource } from "@/hooks/useBlogFeed"
import { formatNumber, formatPercent } from "@/utils/format"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Toggle } from "@/components/ui/toggle"
import {
  Sidebar, SidebarContent, SidebarGroup, SidebarGroupAction, SidebarGroupContent,
  SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar"
import type { WatchlistItem } from "@/types"

/**
 * 팔로우 레일 — shadcn Sidebar(side=right, collapsible=offcanvas) 기반.
 * 넓은 데스크톱=펼침, 그 이하=토글/오버레이(모바일 Sheet). 토글은 헤더의 패널 버튼(⌘B).
 * 종목·채널·블로그는 같은 프리미티브("내가 팔로우하는 대상"): 행=도시에 이동, hover=수집 토글, [+]=추가.
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
  return (
    <Collapsible defaultOpen className="group/section">
      <SidebarGroup className="py-1">
        <SidebarGroupLabel asChild>
          <CollapsibleTrigger className="text-xs font-semibold text-sidebar-foreground/70 hover:text-sidebar-foreground">
            <ChevronDown className="mr-1 h-3 w-3 transition-transform group-data-[state=closed]/section:-rotate-90" />
            {title}
            <span className="ml-1 font-normal text-muted-foreground tabular-nums">{count}</span>
          </CollapsibleTrigger>
        </SidebarGroupLabel>
        <SidebarGroupAction onClick={onAdd} title={addLabel}>
          <Plus className="h-3 w-3" />
        </SidebarGroupAction>
        <CollapsibleContent>
          <SidebarGroupContent>{children}</SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
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
    <SidebarMenuItem className="group/row relative">
      <SidebarMenuButton isActive={active} onClick={onClick} className="h-auto py-1.5 pr-8">
        <div className="min-w-0 flex-1">
          <div className={cn(
            "flex items-center gap-1 text-[13px] truncate",
            active ? "font-semibold" : ""
          )}>
            {warning && (
              <span className="h-1.5 w-1.5 rounded-full bg-destructive shrink-0" title="7일간 유입 없음" />
            )}
            {name}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground truncate">{sub}</div>
        </div>
      </SidebarMenuButton>
      {right && (
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2">{right}</div>
      )}
    </SidebarMenuItem>
  )
}

function SourceToggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <Toggle
      pressed={active}
      onPressedChange={onToggle}
      onClick={(e) => e.stopPropagation()}
      className={cn(
        "shrink-0 h-[18px] w-[18px] min-w-0 p-0 rounded-full border-2 flex items-center justify-center transition-all",
        "opacity-0 group-hover/row:opacity-100 hover:bg-transparent",
        active
          ? "border-primary data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          : "border-muted-foreground/30 opacity-40 group-hover/row:opacity-100"
      )}
      title={active ? "숨기기 — 내 피드·답변에서 제외" : "표시하기"}
    >
      {active && <span className="text-[9px] leading-none">✓</span>}
    </Toggle>
  )
}

function AddForm({ placeholder, onSubmit, pending }: {
  placeholder: string
  onSubmit: (value: string) => void
  pending: boolean
}) {
  return (
    <form
      className="px-2 pb-2 flex gap-1"
      onSubmit={(e) => {
        e.preventDefault()
        const v = new FormData(e.currentTarget).get("v")?.toString().trim()
        if (v) {
          onSubmit(v)
          ;(e.target as HTMLFormElement).reset()
        }
      }}
    >
      <Input name="v" placeholder={placeholder} disabled={pending} autoFocus
        className="min-w-0 flex-1 h-7 px-2 text-[11px]" />
      <Button type="submit" size="sm" disabled={pending} className="shrink-0 h-7 px-2 text-[11px]">
        {pending ? "…" : "추가"}
      </Button>
    </form>
  )
}

function EmptyRow({ message }: { message: string }) {
  return <p className="px-2 py-2 text-[11px] text-muted-foreground">{message}</p>
}

/* ---------- 섹션들 ---------- */

function StockSection({ currentStockCode }: { currentStockCode: string | null }) {
  const navigate = useNavigate()
  const { data: items = [], isLoading } = useWatchlist()
  if (isLoading) return <div className="px-3 py-2"><Skeleton className="h-4 w-full" /></div>

  return (
    <Section title="종목" count={items.length} onAdd={() => navigate("/follow")} addLabel="워치리스트 관리">
      <SidebarMenu>
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
      </SidebarMenu>
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
      <SidebarMenu>
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
      </SidebarMenu>
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
      <SidebarMenu>
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
      </SidebarMenu>
    </Section>
  )
}

/* ---------- 레일 ---------- */

export default function FollowRail({ currentStockCode }: { currentStockCode: string | null }) {
  return (
    <Sidebar side="right" collapsible="offcanvas">
      <SidebarHeader className="px-3 pt-3 pb-1">
        <span className="text-[11px] font-semibold tracking-wide text-muted-foreground">팔로우</span>
      </SidebarHeader>
      <SidebarContent className="gap-0">
        <StockSection currentStockCode={currentStockCode} />
        <ChannelSection />
        <BlogSection />
      </SidebarContent>
    </Sidebar>
  )
}
