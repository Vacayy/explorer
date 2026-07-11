import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Search, X } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { unfollowEntity, spineKeys } from "@/api/spine"
import { useWatchlist } from "@/hooks/useWatchlist"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import { useTelegramChannels, useToggleTelegramChannel } from "@/hooks/useTelegram"
import { useBlogSources, useToggleBlogSource } from "@/hooks/useBlogFeed"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { PageContainer } from "@/components/shared/PageContainer"
import { formatNumber, formatPercent } from "@/utils/format"
import { cn } from "@/lib/utils"
import type { WatchlistItem } from "@/types"

/**
 * /follow — 팔로우 허브 (L1). 내가 따라가는 모든 것: 종목·채널·블로그·태그.
 * 행 클릭 = 도시에 (종목→/analyze, 소스→/source, 태그→피드 필터).
 * 새 소스 종류(유튜브·리포트 등)가 늘면 여기에 섹션이 추가된다.
 */
export default function FollowPage() {
  const navigate = useNavigate()

  return (
    <PageContainer>
      <h2 className="text-xl font-bold">팔로우</h2>

      <StocksSection onGo={(code) => navigate(`/analyze/${code}/summary`)} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
        <ChannelsCard onGo={(key) => navigate(`/source?kind=telegram&key=${encodeURIComponent(key)}`)} />
        <BlogsCard onGo={(key) => navigate(`/source?kind=blog&key=${encodeURIComponent(key)}`)} />
      </div>

      <FollowedTagsCard onGo={(type, name) =>
        navigate(`/feed?${type === "sector" ? "industry" : "topic"}=${encodeURIComponent(name)}`)} />
    </PageContainer>
  )
}

/* ── 종목 (워치리스트 + 전체 검색) ── */

function StocksSection({ onGo }: { onGo: (code: string) => void }) {
  const [query, setQuery] = useState("")
  const { data: items = [], isLoading } = useWatchlist()
  const { data: results = [] } = useCompanySearch(query)

  return (
    <Card>
      <CardHeader className="pb-2 flex-row items-center gap-3">
        <CardTitle className="text-sm">종목 <span className="font-normal text-muted-foreground">{items.length}</span></CardTitle>
        <div className="relative ml-auto w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="전체 상장사 검색…" className="pl-8 h-8 text-sm" />
          {query.trim().length >= 1 && results.length > 0 && (
            <Card className="absolute z-10 mt-1 w-full">
              <CardContent className="py-1 px-0">
                {results.slice(0, 8).map((c) => (
                  <button key={c.corp_code}
                    onClick={() => c.stock_code && onGo(c.stock_code)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted/60 text-left">
                    <span className="font-medium">{c.corp_name}</span>
                    <span className="ml-auto text-xs text-muted-foreground tabular-nums">{c.stock_code}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-0 pb-1">
        {isLoading && <div className="px-4 py-3 space-y-2"><Skeleton className="h-5 w-full" /><Skeleton className="h-5 w-3/4" /></div>}
        {!isLoading && items.length === 0 && (
          <p className="px-4 py-5 text-sm text-muted-foreground text-center">
            워치리스트가 비어 있습니다 — 검색으로 종목에 들어가 ★를 눌러보세요.
          </p>
        )}
        {items.map((item: WatchlistItem) => (
          <button
            key={item.id}
            onClick={() => onGo(item.stock_code)}
            className="flex w-full items-center gap-3 px-4 py-2 hover:bg-muted/50 text-left border-b border-border/50 last:border-0"
          >
            <span className="text-amber-400 text-[10px] tracking-tighter shrink-0">
              {"★".repeat(item.conviction)}{"☆".repeat(5 - item.conviction)}
            </span>
            <span className="text-sm font-medium">{item.corp_name}</span>
            <span className="text-xs text-muted-foreground tabular-nums">{item.stock_code}</span>
            <span className="ml-auto text-xs tabular-nums">
              {item.latest_close != null ? formatNumber(item.latest_close) : "-"}
            </span>
            {item.gap_pct != null && (
              <span className={cn("text-xs font-medium tabular-nums w-16 text-right",
                item.gap_pct >= 0 ? "text-emerald-500" : "text-rose-500")}>
                {formatPercent(item.gap_pct)}
              </span>
            )}
          </button>
        ))}
      </CardContent>
    </Card>
  )
}

/* ── 소스 공통 조각 ── */

function useSourcesHealth() {
  return useQuery({
    queryKey: ["spine", "sources", "health"],
    queryFn: async () => (await api.get("/api/spine/sources/health")).data as {
      items: { kind: string; key: string; docs_7d: number; warning: boolean }[]
    },
    staleTime: 5 * 60_000,
  })
}

function SourceRow({ name, sub, warning, active, onClick, onToggle }: {
  name: string
  sub: string
  warning?: boolean
  active: boolean
  onClick: () => void
  onToggle: () => void
}) {
  return (
    <div onClick={onClick}
      className="group flex items-center gap-2 px-4 py-2 hover:bg-muted/50 cursor-pointer border-b border-border/50 last:border-0">
      <div className="min-w-0 flex-1">
        <div className={cn("text-sm font-medium truncate flex items-center gap-1.5", !active && "opacity-50")}>
          {warning && <span className="h-1.5 w-1.5 rounded-full bg-destructive shrink-0" title="7일간 유입 없음" />}
          {name}
        </div>
        <div className="text-[11px] text-muted-foreground">{sub}</div>
      </div>
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
    </div>
  )
}

function AddForm({ placeholder, onSubmit, pending }: {
  placeholder: string
  onSubmit: (v: string) => void
  pending: boolean
}) {
  return (
    <form className="px-4 pb-2 flex gap-1.5"
      onSubmit={(e) => {
        e.preventDefault()
        const v = new FormData(e.currentTarget).get("v")?.toString().trim()
        if (v) { onSubmit(v); (e.target as HTMLFormElement).reset() }
      }}>
      <Input name="v" placeholder={placeholder} disabled={pending} className="h-7 text-xs" />
      <button type="submit" disabled={pending}
        className="shrink-0 h-7 px-2.5 rounded-md bg-primary text-primary-foreground text-xs disabled:opacity-50">
        {pending ? "…" : "추가"}
      </button>
    </form>
  )
}

/* ── 텔레그램 채널 ── */

function ChannelsCard({ onGo }: { onGo: (key: string) => void }) {
  const { data: channels = [], isLoading } = useTelegramChannels()
  const { data: health } = useSourcesHealth()
  const healthMap = new Map((health?.items ?? []).filter((i) => i.kind === "telegram").map((i) => [i.key, i]))
  const toggle = useToggleTelegramChannel()
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async (channel: string) =>
      (await api.post("/api/spine/sources/telegram", { channel })).data as { channel: string; preview_messages: number },
    onSuccess: (d) => {
      toast.success(`@${d.channel} 등록 — 백그라운드 수집 시작`)
      qc.invalidateQueries({ queryKey: ["telegram-channels"] })
    },
    onError: (e: unknown) => {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "채널 등록 실패")
    },
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">텔레그램 채널 <span className="font-normal text-muted-foreground">{channels.length}</span></CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2 space-y-1">
        <AddForm placeholder="t.me/채널명 또는 @채널명" onSubmit={(v) => add.mutate(v)} pending={add.isPending} />
        {isLoading && <div className="px-4 py-2"><Skeleton className="h-4 w-full" /></div>}
        {channels.map((ch) => {
          const h = healthMap.get(ch.channel_name)
          return (
            <SourceRow key={ch.id}
              name={ch.display_name ?? ch.channel_name}
              sub={`7일 ${h?.docs_7d ?? "-"}건`}
              warning={h?.warning}
              active={ch.is_active === 1}
              onClick={() => onGo(ch.channel_name)}
              onToggle={() => toggle.mutate({ id: ch.id, is_active: !(ch.is_active === 1) })}
            />
          )
        })}
      </CardContent>
    </Card>
  )
}

/* ── 블로그 ── */

function BlogsCard({ onGo }: { onGo: (key: string) => void }) {
  const { data: sources = [], isLoading } = useBlogSources()
  const { data: health } = useSourcesHealth()
  const healthMap = new Map((health?.items ?? []).filter((i) => i.kind === "blog").map((i) => [i.key, i]))
  const toggle = useToggleBlogSource()
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async (url: string) =>
      (await api.post("/api/spine/sources/blog", { url })).data as { url: string; blog_name: string | null },
    onSuccess: (d) => {
      toast.success(`'${d.blog_name || d.url}' 등록 — 백그라운드 수집 시작`)
      qc.invalidateQueries({ queryKey: ["blog-sources"] })
    },
    onError: (e: unknown) => {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "블로그 등록 실패")
    },
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">블로그 <span className="font-normal text-muted-foreground">{sources.length}</span></CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2 space-y-1">
        <AddForm placeholder="블로그 URL (네이버/티스토리/RSS)" onSubmit={(v) => add.mutate(v)} pending={add.isPending} />
        {isLoading && <div className="px-4 py-2"><Skeleton className="h-4 w-full" /></div>}
        {sources.map((src) => {
          const h = healthMap.get(src.url)
          return (
            <SourceRow key={src.id}
              name={src.blog_name || src.url}
              sub={`${src.author ?? src.platform} · 7일 ${h?.docs_7d ?? "-"}건`}
              warning={h?.warning}
              active={src.is_active === 1}
              onClick={() => onGo(src.url)}
              onToggle={() => toggle.mutate({ id: src.id, is_active: !(src.is_active === 1) })}
            />
          )
        })}
      </CardContent>
    </Card>
  )
}

/* ── 팔로우 태그 (섹터·테마) ── */

function FollowedTagsCard({ onGo }: { onGo: (type: string, name: string) => void }) {
  const qc = useQueryClient()
  const { data: follows = [] } = useQuery({
    queryKey: ["spine", "follows"],
    queryFn: async () => (await api.get("/api/spine/follows")).data as
      { entity_id: number; type: string; name: string }[],
    staleTime: 60_000,
  })
  const unfollow = useMutation({
    mutationFn: unfollowEntity,
    onSuccess: () => {
      toast.success("팔로우 해제 — 홈 업데이트에서 제외됩니다")
      qc.invalidateQueries({ queryKey: ["spine", "follows"] })
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">태그 팔로우 <span className="font-normal text-muted-foreground">{follows.length}</span></CardTitle>
      </CardHeader>
      <CardContent>
        {follows.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            팔로우한 산업·테마가 없습니다 — 피드에서 태그 필터 후 "이 태그 팔로우"를 눌러보세요.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {follows.map((f) => (
              <Badge key={f.entity_id} variant="secondary" className="text-xs gap-1 pr-1 cursor-pointer"
                onClick={() => onGo(f.type, f.name)}>
                {f.name}
                <button
                  onClick={(e) => { e.stopPropagation(); unfollow.mutate(f.entity_id) }}
                  className="hover:text-destructive" aria-label="팔로우 해제">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
