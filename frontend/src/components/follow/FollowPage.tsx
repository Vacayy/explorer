import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Search, X } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { unfollowEntity, spineKeys } from "@/api/spine"
import { apiQuery, STALE } from "@/api/query"
import { useWatchlist, useUpdateWatchlistItem, useDeleteWatchlistItem } from "@/hooks/useWatchlist"
import { useQuotes, type LiveQuote } from "@/hooks/useQuotes"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import { useTelegramChannels, useToggleTelegramChannel } from "@/hooks/useTelegram"
import { useBlogSources, useToggleBlogSource, type BlogSource } from "@/hooks/useBlogFeed"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { PageContainer } from "@/components/shared/PageContainer"
import { formatKrw, formatNumber } from "@/utils/format"
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

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 items-start">
        <ChannelsCard onGo={(key) => navigate(`/source?kind=telegram&key=${encodeURIComponent(key)}`)} />
        <BlogSourcesCard title="블로그" placeholder="네이버/티스토리 블로그 URL"
          match={(s) => s.platform !== "rss"}
          onGo={(key) => navigate(`/source?kind=blog&key=${encodeURIComponent(key)}`)} />
        <BlogSourcesCard title="뉴스 및 아티클" placeholder="RSS 피드 URL (뉴스·뉴스레터)"
          match={(s) => s.platform === "rss"}
          onGo={(key) => navigate(`/source?kind=blog&key=${encodeURIComponent(key)}`)} />
        <YouTubeCard onGo={(cid) => navigate(`/source?kind=youtube&key=${encodeURIComponent(cid)}`)} />
      </div>

      <FollowedPeopleCard onGo={(name) => navigate(`/person?name=${encodeURIComponent(name)}`)} />

      <FollowedTagsCard onGo={(type, name) =>
        navigate(`/feed?${type === "sector" ? "industry" : "topic"}=${encodeURIComponent(name)}`)} />
    </PageContainer>
  )
}

/* ── 종목 (워치리스트 관리 통합: 정렬·편집·삭제 + 전체 검색) ── */

type SortKey = "corp_name" | "latest_close" | "latest_market_cap"

function StocksSection({ onGo }: { onGo: (code: string) => void }) {
  const [query, setQuery] = useState("")
  const [sortKey, setSortKey] = useState<SortKey>("latest_market_cap")
  const [sortAsc, setSortAsc] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const { data: items = [], isLoading } = useWatchlist()
  const { data: results = [] } = useCompanySearch(query)
  const update = useUpdateWatchlistItem()
  const del = useDeleteWatchlistItem()
  const { data: quotes } = useQuotes(items.map((i) => i.stock_code))
  const quoteMap = new Map((quotes ?? []).map((q) => [q.stock_code, q]))

  const sorted = [...items].sort((a, b) => {
    const va = a[sortKey], vb = b[sortKey]
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number)
    return sortAsc ? cmp : -cmp
  })

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(key === "corp_name") }
  }
  const arrow = (key: SortKey) => sortKey === key ? (sortAsc ? " ↑" : " ↓") : ""

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
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="px-4 py-1.5 text-left font-medium cursor-pointer select-none" onClick={() => toggleSort("corp_name")}>
                  종목명{arrow("corp_name")}
                </th>
                <th className="py-1.5 text-left font-medium">코드</th>
                <th className="py-1.5 text-right font-medium cursor-pointer select-none" onClick={() => toggleSort("latest_close")}>
                  현재가{arrow("latest_close")}
                </th>
                <th className="py-1.5 text-right font-medium cursor-pointer select-none" onClick={() => toggleSort("latest_market_cap")}>
                  시가총액{arrow("latest_market_cap")}
                </th>
                <th className="px-4 py-1.5 text-right font-medium w-24"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((item) => (
                <StockRow key={item.id} item={item} quote={quoteMap.get(item.stock_code)}
                  editing={editingId === item.id}
                  onEdit={() => setEditingId(editingId === item.id ? null : item.id)}
                  onSaved={() => setEditingId(null)}
                  onGo={() => onGo(item.stock_code)}
                  onDelete={() => del.mutate(item.id, { onSuccess: () => toast.success(`'${item.corp_name}' 워치리스트에서 삭제`) })}
                  update={update}
                />
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}

function StockRow({ item, quote, editing, onEdit, onSaved, onGo, onDelete, update }: {
  item: WatchlistItem
  quote?: LiveQuote
  editing: boolean
  onEdit: () => void
  onSaved: () => void
  onGo: () => void
  onDelete: () => void
  update: ReturnType<typeof useUpdateWatchlistItem>
}) {
  return (
    <>
      <tr className="border-b border-border/50 hover:bg-muted/50 cursor-pointer" onClick={onGo}>
        <td className="px-4 py-2 font-medium">{item.corp_name}</td>
        <td className="py-2 text-xs text-muted-foreground tabular-nums">{item.stock_code}</td>
        <td className="py-2 text-right tabular-nums text-xs">
          {quote?.price != null ? (
            <>
              {formatNumber(quote.price)}
              {quote.change_pct != null && (
                <span className={`ml-1.5 ${quote.change_pct >= 0 ? "text-up" : "text-down"}`}>
                  {quote.change_pct >= 0 ? "+" : ""}{quote.change_pct.toFixed(1)}%
                </span>
              )}
            </>
          ) : item.latest_close != null ? formatNumber(item.latest_close) : "-"}
        </td>
        <td className="py-2 text-right tabular-nums text-xs">
          {item.latest_market_cap != null ? formatKrw(item.latest_market_cap) : "-"}
        </td>
        <td className="px-4 py-2 text-right">
          <button onClick={(e) => { e.stopPropagation(); onEdit() }}
            className="text-[11px] text-muted-foreground hover:text-foreground mr-2">편집</button>
          <button onClick={(e) => { e.stopPropagation(); onDelete() }}
            className="text-[11px] text-muted-foreground hover:text-destructive">삭제</button>
        </td>
      </tr>
      {editing && (
        <tr className="border-b border-border/50 bg-muted/30">
          <td colSpan={5} className="px-4 py-2">
            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                const fd = new FormData(e.currentTarget)
                const tp = fd.get("tp")?.toString().trim()
                update.mutate(
                  { id: item.id, target_price: tp ? Number(tp.replace(/,/g, "")) : undefined,
                    thesis: fd.get("thesis")?.toString() ?? undefined },
                  { onSuccess: () => { toast.success("저장됨 — 논지는 AI 브리프의 점검 대상이 됩니다"); onSaved() } },
                )
              }}
            >
              <label className="text-[11px] text-muted-foreground">목표가</label>
              <Input name="tp" defaultValue={item.target_price ?? ""} className="h-7 w-28 text-xs" placeholder="원" />
              <label className="text-[11px] text-muted-foreground">투자 논지</label>
              <Input name="thesis" defaultValue={item.thesis ?? ""} className="h-7 flex-1 min-w-[200px] text-xs"
                placeholder="핵심 논지 한 줄 — AI 브리프가 새 증거와 대조합니다" />
              <button type="submit" disabled={update.isPending}
                className="h-7 px-2.5 rounded-md bg-primary text-primary-foreground text-xs disabled:opacity-50">저장</button>
            </form>
          </td>
        </tr>
      )}
    </>
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
        title={active ? "숨기기 — 내 피드·답변에서 제외" : "표시하기"}
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

/* ── 유튜브 (채널 구독 + 영상 링크 단건) ── */

interface YtChannel { channel_id: string; title: string | null; handle: string | null; is_active: boolean }

function YouTubeCard({ onGo }: { onGo: (channelId: string) => void }) {
  const qc = useQueryClient()
  const { data } = useQuery(
    apiQuery<{ items: YtChannel[] }>({ key: ["youtube-channels"], url: "/api/spine/sources/youtube", staleTime: STALE.medium }),
  )
  const channels = data?.items ?? []
  const add = useMutation({
    mutationFn: async (input: string) =>
      (await api.post("/api/spine/sources/youtube", { input })).data as { kind: string; title?: string },
    onSuccess: (d) => {
      toast.success(d.kind === "channel" ? `'${d.title}' 구독 — 최근 영상 자막 수집` : "영상 자막 수집 시작")
      qc.invalidateQueries({ queryKey: ["youtube-channels"] })
    },
    onError: (e: unknown) =>
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "등록 실패"),
  })
  const toggle = useMutation({
    mutationFn: async ({ id, active }: { id: string; active: boolean }) =>
      api.patch(`/api/spine/sources/youtube/${id}?is_active=${active}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["youtube-channels"] }),
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">유튜브 <span className="font-normal text-muted-foreground">{channels.length}</span></CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2 space-y-1">
        <AddForm placeholder="채널 @handle·URL (구독) 또는 영상 URL (단건)" onSubmit={(v) => add.mutate(v)} pending={add.isPending} />
        {channels.map((ch) => (
          <SourceRow key={ch.channel_id}
            name={ch.title ?? ch.channel_id}
            sub="신규 영상 자동 자막"
            active={ch.is_active}
            onClick={() => onGo(ch.channel_id)}
            onToggle={() => toggle.mutate({ id: ch.channel_id, active: !ch.is_active })}
          />
        ))}
      </CardContent>
    </Card>
  )
}

/* ── 블로그 / 뉴스·아티클 (blog_sources를 platform으로 분리) ── */

function BlogSourcesCard({ title, placeholder, match, onGo }: {
  title: string
  placeholder: string
  match: (src: BlogSource) => boolean
  onGo: (key: string) => void
}) {
  const { data: allSources = [], isLoading } = useBlogSources()
  const sources = allSources.filter(match)
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
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "소스 등록 실패")
    },
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title} <span className="font-normal text-muted-foreground">{sources.length}</span></CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2 space-y-1">
        <AddForm placeholder={placeholder} onSubmit={(v) => add.mutate(v)} pending={add.isPending} />
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

/* ── 팔로우 인물 ── */

function FollowedPeopleCard({ onGo }: { onGo: (name: string) => void }) {
  const qc = useQueryClient()
  const { data: follows = [] } = useQuery({
    queryKey: ["spine", "follows"],
    queryFn: async () => (await api.get("/api/spine/follows")).data as
      { entity_id: number; type: string; name: string }[],
    staleTime: 60_000,
  })
  const people = follows.filter((f) => f.type === "person")
  const unfollow = useMutation({
    mutationFn: unfollowEntity,
    onSuccess: () => {
      toast.success("팔로우 해제")
      qc.invalidateQueries({ queryKey: ["spine", "follows"] })
      qc.invalidateQueries({ queryKey: spineKeys.home() })
    },
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">인물 <span className="font-normal text-muted-foreground">{people.length}</span></CardTitle>
      </CardHeader>
      <CardContent>
        {people.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            팔로우한 인물이 없습니다 — 피드·문서의 인물 칩에서 프로필로 들어가 팔로우해보세요.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {people.map((f) => (
              <Badge key={f.entity_id} variant="outline" className="text-xs gap-1 pr-1 cursor-pointer text-hypothesis border-hypothesis/40 hover:bg-hypothesis/10"
                onClick={() => onGo(f.name)}>
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

/* ── 팔로우 태그 (섹터·테마) ── */

function FollowedTagsCard({ onGo }: { onGo: (type: string, name: string) => void }) {
  const qc = useQueryClient()
  const { data: allFollows = [] } = useQuery({
    queryKey: ["spine", "follows"],
    queryFn: async () => (await api.get("/api/spine/follows")).data as
      { entity_id: number; type: string; name: string }[],
    staleTime: 60_000,
  })
  const follows = allFollows.filter((f) => f.type !== "person")
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
