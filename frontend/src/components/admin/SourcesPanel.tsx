import type { ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { apiQuery, STALE, toApiError } from "@/api/query"
import { useTelegramChannels, useToggleTelegramChannel } from "@/hooks/useTelegram"
import { useBlogSources, useToggleBlogSource, type BlogSource } from "@/hooks/useBlogFeed"
import { useRefreshSource } from "@/hooks/useRefreshSource"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import { ErrorState } from "@/components/shared/ErrorState"
import { RefreshButton } from "@/components/shared/RefreshButton"
import { InfoTip } from "@/components/regimes/Section"
import { sourcesSummary } from "@/lib/sources"
import { cn } from "@/lib/utils"
import { formatKstDateTime, formatNumber } from "@/utils/format"

/** 소스 계기판 한 행 — 유입(7일/24h)에 **소비 지표 30일**을 더한 것 (D-127) */
export interface SourceHealthItem {
  kind: string
  key: string
  name: string
  is_active: boolean
  collect_enabled: boolean
  docs_7d: number
  docs_24h: number
  warning: boolean
  docs_30d: number
  untagged_30d: number
  stock_linked_30d: number
  causal_30d: number
  last_fetch_at: string | null
  shared_domain: boolean
}

/**
 * 관리자 › 소스 (/admin/sources · 옛 /sources · 시안 Feed-Sources · ia-redesign §4.26).
 * 요약 4칸(보기 전용) → 네 칸(텔레그램·블로그·뉴스 및 아티클·유튜브): 추가 입력 + 목록(칸 안 스크롤).
 * 줄 = 이름 · 7일·30일 유입과 소비 지표 · 유입 없음 점 · 수집 꺼짐 배지 · 도메인 공유. 마우스를 올리면 지금 수집·수집 중단/재개, 오른쪽 스위치 = 표시.
 * 건강 지표가 실패하면 줄의 지표만 '-'로 두고 목록·스위치는 그대로(§4.28 부분).
 */
export function SourcesPanel() {
  const navigate = useNavigate()
  const health = useSourcesHealth()
  const go = (kind: string, key: string) => navigate(`/source?kind=${kind}&key=${encodeURIComponent(key)}`)
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center gap-1">
      <h2 className="text-section font-semibold">소스</h2>
      <InfoTip label="소스 설명">피드에서 읽을 채널·블로그·유튜브를 관리합니다. 스위치(표시)는 내 피드·답변에 보일지만 정하고, 수집 중단은 새 글 수집만 멈춥니다. 둘은 따로 동작하고 모아 둔 문서·이력은 지우지 않습니다.</InfoTip>
      {health.data && <span className="ml-auto font-mono text-caption tabular-nums text-muted-foreground">{formatKstDateTime(health.data.as_of)} 기준</span>}
    </div>
    <SummaryStrip health={health} />
    <div className="surface-grid grid grid-cols-1 lg:grid-cols-2">
      <ChannelsColumn health={health.data?.items} onGo={key => go("telegram", key)} />
      <BlogColumn title="블로그" placeholder="네이버/티스토리 블로그 URL" match={s => s.platform !== "rss"} health={health.data?.items} onGo={key => go("blog", key)} />
      <BlogColumn title="뉴스 및 아티클" placeholder="RSS 피드 URL (뉴스·뉴스레터)" match={s => s.platform === "rss"} health={health.data?.items} onGo={key => go("blog", key)} />
      <YouTubeColumn health={health.data?.items} onGo={cid => go("youtube", cid)} />
    </div>
  </div>
}

function useSourcesHealth() {
  return useQuery({
    queryKey: ["spine", "sources", "health"],
    queryFn: async () => (await api.get("/api/spine/sources/health")).data as { items: SourceHealthItem[]; as_of: string },
    staleTime: 5 * 60_000,
  })
}

/** 맨 위 요약 4칸 — 보는 용도일 뿐 할 일 목록으로 만들지 않는다(유입 없는 소스도 수집은 계속 시도한다) */
function SummaryStrip({ health }: { health: ReturnType<typeof useSourcesHealth> }) {
  if (health.isLoading) return <Skeleton className="h-24 w-full" />
  if (!health.data) return null   // 실패하면 요약만 생략 — 칸별 목록은 그대로
  const s = sourcesSummary(health.data.items)
  const cell = (label: string, value: number, sub?: ReactNode) => <div className="min-w-0 border-r p-4 last:border-r-0 max-md:border-b max-md:even:border-r-0">
    <div className="text-caption text-muted-foreground">{label}</div>
    <div className="mt-1 font-mono text-2xl tabular-nums">{formatNumber(value)}</div>
    {sub && <div className="mt-1 truncate text-caption text-muted-foreground">{sub}</div>}
  </div>
  return <div className="grid grid-cols-2 border bg-card md:grid-cols-4" data-sources-summary>
    {cell("소스", s.total, `텔레그램 ${s.byKind.telegram ?? 0} · 블로그·뉴스 ${s.byKind.blog ?? 0} · 유튜브 ${s.byKind.youtube ?? 0}`)}
    {cell("지난 7일 유입", s.docs7d, "피드에 들어온 글")}
    {cell("7일간 유입 없음", s.quiet)}
    {cell("수집 꺼짐", s.collectOff, "문서·이력은 보존")}
  </div>
}

/** 수집 축 토글 — is_active(표시)와 독립 (D-126) */
function useToggleCollect() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { kind: string; key: string; enabled: boolean }) =>
      (await api.post("/api/spine/sources/collect", v)).data,
    onSuccess: (_d, v) => {
      toast.success(v.enabled ? "수집을 다시 시작합니다" : "수집을 멈췄습니다 — 문서·이력은 보존됩니다")
      qc.invalidateQueries({ queryKey: ["spine", "sources", "health"] })
    },
    onError: () => toast.error("수집 설정을 바꾸지 못했습니다"),
  })
}

function SourceRow({ name, sub, active, health, onClick, onToggle, onToggleCollect, onRefresh, refreshing }: {
  name: string
  sub?: string | null
  active: boolean
  health?: SourceHealthItem
  onClick: () => void
  onToggle: () => void
  onToggleCollect: () => void
  /** 지금 수집 (D-199) — cron을 기다리지 않고 이 소스만 수집 */
  onRefresh: () => void
  refreshing: boolean
}) {
  // 소비 지표 — 30일 수집량 대비 무엇이 실제로 쓰였나 (D-127). 지표가 없으면(건강 지표 실패) '-'
  const collecting = health?.collect_enabled !== false
  const n = health?.docs_30d ?? 0
  const pct = (v: number) => (n ? Math.round((v / n) * 100) : 0)
  const metrics = !health ? "7일 -" : [
    `7일 ${formatNumber(health.docs_7d)}건`,
    n > 0 && `30일 ${formatNumber(n)} · 종목 ${pct(health.stock_linked_30d)}% · 인과 ${pct(health.causal_30d)}%`,
  ].filter(Boolean).join(" · ")
  return (
    <div className="group flex min-h-14 cursor-pointer items-center gap-2 border-b px-4 py-2 last:border-0 hover:bg-muted/50" onClick={onClick} data-source-row>
      <div className={cn("min-w-0 flex-1", !active && "opacity-50")}>
        <div className="flex items-center gap-1.5 truncate text-sm font-medium">
          {health?.warning && <span className="size-1.5 shrink-0 rounded-full bg-destructive" role="img" aria-label="7일간 유입 없음" />}
          {!collecting && <Badge variant="secondary" className="shrink-0 text-[10px] font-normal">수집 꺼짐</Badge>}
          <span className="truncate">{name}</span>
        </div>
        <div className="truncate text-[11px] text-muted-foreground">
          {sub && `${sub} · `}{metrics}
          {health && health.untagged_30d > 0 && n > 0 && <span className="text-hypothesis"> · 태깅실패 {pct(health.untagged_30d)}%</span>}
          {health?.shared_domain && <span className="text-hypothesis" title="같은 도메인 피드가 여럿이라 그 피드들의 문서가 함께 집계된 값입니다"> · 도메인 공유(중복집계)</span>}
        </div>
      </div>
      {/* 행 조작은 마우스를 올리면 드러나고, 터치(pointer-coarse)는 항상 보인다. 진행 중인 수집은 항상 보인다 */}
      <div onClick={e => e.stopPropagation()} className={cn("flex shrink-0 items-center gap-1 transition-opacity", refreshing ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 pointer-coarse:opacity-100")}>
        <RefreshButton onClick={onRefresh} pending={refreshing} title={`${name} 지금 수집 — 새 글만 가져와 태깅합니다`} />
        <Button variant="outline" size="xs" className={cn(!collecting && "border-hypothesis/40 text-hypothesis")} onClick={onToggleCollect}
          aria-label={`${name} ${collecting ? "수집 중단" : "수집 재개"}`}>
          {collecting ? "수집 중단" : "수집 재개"}
        </Button>
      </div>
      <span onClick={e => e.stopPropagation()} className="flex shrink-0 items-center">
        <Switch checked={active} onCheckedChange={onToggle} aria-label={`${name} 표시`} />
      </span>
    </div>
  )
}

function AddForm({ placeholder, onSubmit, pending }: { placeholder: string; onSubmit: (v: string) => void; pending: boolean }) {
  return (
    <form className="flex gap-1.5 border-b px-4 pb-3"
      onSubmit={(e) => {
        e.preventDefault()
        const v = new FormData(e.currentTarget).get("v")?.toString().trim()
        if (v) { onSubmit(v); e.currentTarget.reset() }
      }}>
      {/* 시안 Feed-Sources: 칸 안 추가 입력은 테두리 사각(모서리 8) + 채운 '추가' */}
      <Input name="v" aria-label={placeholder} placeholder={placeholder} disabled={pending} className="h-8 rounded-lg border border-line-2 bg-transparent px-2.5 text-[12.5px]" />
      <Button type="submit" size="sm" disabled={pending} className="h-8 shrink-0 rounded-lg text-[12.5px]">{pending ? "추가 중…" : "추가"}</Button>
    </form>
  )
}

/** 한 칸 — 머리(이름·개수) · 추가 입력 · 목록(칸 안 스크롤). 칸 단위로 실패한다(나머지 칸은 보임) */
function Column({ title, count, add, loading, error, onRetry, children }: {
  title: string; count?: number; add: ReactNode; loading: boolean; error: boolean; onRetry: () => void; children: ReactNode
}) {
  return <section aria-label={title} className="flex min-w-0 flex-col bg-card">
    <h3 className="flex items-baseline gap-2 px-4 pb-3 pt-4 text-card-title font-semibold">{title}{count != null && <span className="font-mono text-caption font-normal tabular-nums text-muted-foreground">{count}</span>}</h3>
    {add}
    <div className="max-h-[560px] overflow-y-auto overscroll-y-contain">
      {loading && <div role="status" aria-label={`${title} 불러오는 중`} className="space-y-3 p-4">{[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-10 w-full" />)}</div>}
      {error && <ErrorState message={`${title} 목록을 불러오지 못했습니다`} onRetry={onRetry} />}
      {!loading && !error && count === 0 && <p className="px-4 py-6 text-sm text-muted-foreground">아직 등록한 소스가 없습니다</p>}
      {children}
    </div>
  </section>
}

function ChannelsColumn({ health, onGo }: { health?: SourceHealthItem[]; onGo: (key: string) => void }) {
  const channels = useTelegramChannels()
  const healthMap = new Map((health ?? []).filter((i) => i.kind === "telegram").map((i) => [i.key, i]))
  const collect = useToggleCollect()
  const refresher = useRefreshSource()
  const toggle = useToggleTelegramChannel()
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async (channel: string) =>
      (await api.post("/api/spine/sources/telegram", { channel })).data as { channel: string; preview_messages: number },
    onSuccess: (d) => {
      toast.success(`@${d.channel} 등록 — 백그라운드에서 수집을 시작합니다`)
      qc.invalidateQueries({ queryKey: ["telegram-channels"] })
    },
    onError: (e: unknown) => toast.error(toApiError(e).message || "채널을 등록하지 못했습니다"),
  })
  const list = channels.data ?? []
  return (
    <Column title="텔레그램 채널" count={channels.data ? list.length : undefined} loading={channels.isLoading} error={channels.isError} onRetry={() => void channels.refetch()}
      add={<AddForm placeholder="t.me/채널명 또는 @채널명" onSubmit={(v) => add.mutate(v)} pending={add.isPending} />}>
      {list.map((ch) => {
        const h = healthMap.get(ch.channel_name)
        const name = ch.display_name ?? ch.channel_name
        return <SourceRow key={ch.id} name={name} active={ch.is_active === 1} health={h}
          onClick={() => onGo(ch.channel_name)}
          onToggle={() => toggle.mutate({ id: ch.id, is_active: !(ch.is_active === 1) })}
          onToggleCollect={() => collect.mutate({ kind: "telegram", key: ch.channel_name, enabled: h?.collect_enabled === false })}
          onRefresh={() => refresher.refresh("telegram", ch.channel_name, name)}
          refreshing={refresher.isRefreshing("telegram", ch.channel_name)} />
      })}
    </Column>
  )
}

export interface YtChannel { channel_id: string; title: string | null; handle: string | null; is_active: boolean }

function YouTubeColumn({ health, onGo }: { health?: SourceHealthItem[]; onGo: (channelId: string) => void }) {
  const qc = useQueryClient()
  const channels = useQuery(
    apiQuery<{ items: YtChannel[] }>({ key: ["youtube-channels"], url: "/api/spine/sources/youtube", staleTime: STALE.medium }),
  )
  const add = useMutation({
    mutationFn: async (input: string) =>
      (await api.post("/api/spine/sources/youtube", { input })).data as { kind: string; title?: string },
    onSuccess: (d) => {
      toast.success(d.kind === "channel" ? `'${d.title}' 구독 — 최근 영상 자막을 수집합니다` : "영상 자막 수집을 시작합니다")
      qc.invalidateQueries({ queryKey: ["youtube-channels"] })
    },
    onError: (e: unknown) => toast.error(toApiError(e).message || "등록하지 못했습니다"),
  })
  const toggle = useMutation({
    mutationFn: async ({ id, active }: { id: string; active: boolean }) =>
      api.patch(`/api/spine/sources/youtube/${id}?is_active=${active}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["youtube-channels"] }),
  })
  const healthMap = new Map((health ?? []).filter((i) => i.kind === "youtube").map((i) => [i.key, i]))
  const collect = useToggleCollect()
  const refresher = useRefreshSource()
  const list = channels.data?.items ?? []
  return (
    <Column title="유튜브" count={channels.data ? list.length : undefined} loading={channels.isLoading} error={channels.isError} onRetry={() => void channels.refetch()}
      add={<AddForm placeholder="채널 @handle·URL (구독) 또는 영상 URL (단건)" onSubmit={(v) => add.mutate(v)} pending={add.isPending} />}>
      {list.map((ch) => {
        const h = healthMap.get(ch.channel_id)
        const name = ch.title ?? ch.channel_id
        return <SourceRow key={ch.channel_id} name={name} active={ch.is_active} health={h}
          onClick={() => onGo(ch.channel_id)}
          onToggle={() => toggle.mutate({ id: ch.channel_id, active: !ch.is_active })}
          onToggleCollect={() => collect.mutate({ kind: "youtube", key: ch.channel_id, enabled: h?.collect_enabled === false })}
          onRefresh={() => refresher.refresh("youtube", ch.channel_id, name)}
          refreshing={refresher.isRefreshing("youtube", ch.channel_id)} />
      })}
    </Column>
  )
}

/** 블로그 / 뉴스·아티클 — blog_sources를 platform으로 나눈다 */
function BlogColumn({ title, placeholder, match, health, onGo }: {
  title: string; placeholder: string; match: (src: BlogSource) => boolean; health?: SourceHealthItem[]; onGo: (key: string) => void
}) {
  const all = useBlogSources()
  const sources = (all.data ?? []).filter(match)
  const healthMap = new Map((health ?? []).filter((i) => i.kind === "blog").map((i) => [i.key, i]))
  const collect = useToggleCollect()
  const refresher = useRefreshSource()
  const toggle = useToggleBlogSource()
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async (url: string) =>
      (await api.post("/api/spine/sources/blog", { url })).data as { url: string; blog_name: string | null },
    onSuccess: (d) => {
      toast.success(`'${d.blog_name || d.url}' 등록 — 백그라운드에서 수집을 시작합니다`)
      qc.invalidateQueries({ queryKey: ["blog-sources"] })
    },
    onError: (e: unknown) => toast.error(toApiError(e).message || "소스를 등록하지 못했습니다"),
  })
  return (
    <Column title={title} count={all.data ? sources.length : undefined} loading={all.isLoading} error={all.isError} onRetry={() => void all.refetch()}
      add={<AddForm placeholder={placeholder} onSubmit={(v) => add.mutate(v)} pending={add.isPending} />}>
      {sources.map((src) => {
        const h = healthMap.get(src.url)
        const name = src.blog_name || src.url
        return <SourceRow key={src.id} name={name} sub={src.author} active={src.is_active === 1} health={h}
          onClick={() => onGo(src.url)}
          onToggle={() => toggle.mutate({ id: src.id, is_active: !(src.is_active === 1) })}
          onToggleCollect={() => collect.mutate({ kind: "blog", key: src.url, enabled: h?.collect_enabled === false })}
          onRefresh={() => refresher.refresh("blog", src.url, name)}
          refreshing={refresher.isRefreshing("blog", src.url)} />
      })}
    </Column>
  )
}
