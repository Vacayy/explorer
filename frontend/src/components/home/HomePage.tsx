import { Link } from "react-router-dom"
import { TrendingUp, CalendarDays, Bell, Building2, Lightbulb, LineChart, X } from "lucide-react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useHome } from "@/hooks/useHome"
import { spineKeys, unfollowEntity } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState, EmptyState } from "@/components/shared/ErrorState"
import { SourceBadge } from "@/components/shared/SourceBadge"
import { FreshnessStamp } from "@/components/shared/FreshnessStamp"
import { formatRelativeTime } from "@/utils/format"
import type { BriefItem, CalendarEvent, HomeFollow, SpineSignal, WatchlistUpdate } from "@/types"

/**
 * /home — 내 종목 follow-up (product-v2.md v2.1)
 * 층위 원칙: 홈은 변화(delta)만 보여준다. 깊이는 클릭 뒤(디테일)에.
 * 빈 화면 방지: 내 종목이 조용한 날은 시장 하이라이트가 위로 승격된다.
 */
export default function HomePage() {
  const { data, isLoading, isError, refetch } = useHome()

  if (isLoading) return <HomeSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const quietDay = !data.watchlist_empty && data.watchlist_updates.length === 0

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-bold">홈</h2>
        <FreshnessStamp asOf={data.as_of} />
      </div>

      {data.briefing.length > 0 && <BriefingSection items={data.briefing} />}

      <CalendarSection events={data.calendar} />

      {/* 조용한 날: 시장 하이라이트를 먼저 올린다 (빈 화면 방지 규칙) */}
      {quietDay ? (
        <>
          <HighlightsSection signals={data.market_highlights} promoted />
          <UpdatesSection updates={data.watchlist_updates} watchlistEmpty={data.watchlist_empty} follows={data.follows} />
        </>
      ) : (
        <>
          <UpdatesSection updates={data.watchlist_updates} watchlistEmpty={data.watchlist_empty} follows={data.follows} />
          <HighlightsSection signals={data.market_highlights} />
        </>
      )}
    </div>
  )
}

/* ---------- ⓪ 기계가 먼저 말하는 3줄 (변화 감지 — 판단 아님) ---------- */

const BRIEF_ICON = {
  insight: Lightbulb,
  action: Building2,
  signal: LineChart,
} as const

function BriefingSection({ items }: { items: BriefItem[] }) {
  return (
    <Card className="border-l-2 border-l-primary">
      <CardContent className="py-3">
        <ul className="space-y-1.5">
          {items.map((b, i) => {
            const Icon = BRIEF_ICON[b.kind as keyof typeof BRIEF_ICON] ?? Lightbulb
            return (
              <li key={i}>
                <Link to={b.to} className="group flex items-start gap-2 text-sm">
                  <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${b.kind === "insight" ? "text-hypothesis" : "text-muted-foreground"}`} />
                  <span className="group-hover:underline leading-snug">{b.text}</span>
                </Link>
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}

/* ---------- ① 캘린더 스트립 ---------- */

function CalendarSection({ events }: { events: CalendarEvent[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <CalendarDays className="h-4 w-4 text-muted-foreground" /> 이번 주 일정
        </CardTitle>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground py-2">이번 주 등록된 일정이 없습니다.</p>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {events.map((e) => (
              <div
                key={e.id}
                className={`shrink-0 rounded-lg border px-3 py-2 min-w-[180px] ${
                  e.in_watchlist ? "border-primary/40 bg-accent" : ""
                }`}
              >
                <div className="text-[11px] text-muted-foreground tabular-nums">{e.event_date}</div>
                <div className="text-sm font-medium truncate max-w-[220px]">{e.title}</div>
                <div className="flex items-center gap-1 mt-1">
                  {e.corp_name && e.stock_code && (
                    <Link to={`/analyze/${e.stock_code}/summary`} className="text-xs text-primary hover:underline">
                      {e.corp_name}
                    </Link>
                  )}
                  {e.in_watchlist && <Badge variant="secondary" className="text-[10px]">내 종목</Badge>}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- ② 내 종목 업데이트 스트림 ---------- */

function UpdatesSection({ updates, watchlistEmpty, follows }: {
  updates: WatchlistUpdate[]; watchlistEmpty: boolean; follows: HomeFollow[]
}) {
  const qc = useQueryClient()
  const unfollow = useMutation({
    mutationFn: unfollowEntity,
    onSuccess: () => qc.invalidateQueries({ queryKey: spineKeys.home() }),
  })
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Bell className="h-4 w-4 text-muted-foreground" /> 내 종목·팔로우 업데이트
        </CardTitle>
        {follows.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {follows.map((f) => (
              <Badge key={f.entity_id} variant="secondary" className="text-[10px] gap-1 pr-1 font-normal">
                {f.name}
                <button onClick={() => unfollow.mutate(f.entity_id)} aria-label="팔로우 해제">
                  <X className="h-2.5 w-2.5" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {watchlistEmpty ? (
          <div className="py-8 text-center space-y-2">
            <p className="text-sm text-muted-foreground">추적 중인 종목이 없습니다.</p>
            <p className="text-xs text-muted-foreground">
              상단 검색으로 기업을 워치리스트에 담거나, 피드에서 산업·토픽 태그를 팔로우하면 업데이트가 여기에 모입니다.
            </p>
            <Link to="/research/watchlist" className="text-xs text-primary hover:underline">
              워치리스트 관리 →
            </Link>
          </div>
        ) : updates.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">
            오늘 내 종목은 조용합니다. 아래는 시장 전체 하이라이트입니다.
          </p>
        ) : (
          <ul className="divide-y">
            {updates.map((u, i) => (
              <UpdateRow key={`${u.kind}-${u.stock_code}-${u.occurred_at}-${i}`} update={u} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function UpdateRow({ update: u }: { update: WatchlistUpdate }) {
  return (
    <li className="flex items-center gap-3 py-2.5">
      {u.kind === "signal" ? (
        <Badge className="shrink-0 text-[10px] bg-hypothesis/15 text-hypothesis border-transparent">신호</Badge>
      ) : (
        <SourceBadge sourceType={u.source_type ?? ""} />
      )}
      <Link
        to={u.entity_type === "company" && u.stock_code
          ? `/analyze/${u.stock_code}/summary`
          : `/feed?${u.entity_type === "theme" ? "topic" : "industry"}=${encodeURIComponent(u.corp_name)}`}
        className="shrink-0 text-sm font-medium text-primary hover:underline"
      >
        {u.corp_name}
      </Link>
      {u.doc_id ? (
        <Link to={`/doc/${u.doc_id}`} className="text-sm truncate hover:underline">
          {u.title}
        </Link>
      ) : (
        <span className="text-sm truncate">{u.title}</span>
      )}
      <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
        {formatRelativeTime(u.occurred_at)}
      </span>
    </li>
  )
}

/* ---------- ③ 시장 하이라이트 (신호) ---------- */

function HighlightsSection({ signals, promoted }: { signals: SpineSignal[]; promoted?: boolean }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <TrendingUp className="h-4 w-4 text-muted-foreground" />
          시장 하이라이트
          {promoted && <span className="text-[11px] font-normal text-muted-foreground">— 오늘 내 종목이 조용해서 먼저 보여드려요</span>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {signals.length === 0 ? (
          <EmptyState message="최근 7일 신호가 없습니다." />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {signals.map((s) => (
              <SignalMiniCard key={s.id} signal={s} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SignalMiniCard({ signal: s }: { signal: SpineSignal }) {
  const p = s.payload
  return (
    <div className="rounded-lg border p-3 space-y-2">
      <div className="flex items-center gap-2">
        {s.stock_code ? (
          <Link to={`/analyze/${s.stock_code}/summary`} className="font-medium text-sm text-primary hover:underline">
            {s.entity_name}
          </Link>
        ) : (
          <span className="font-medium text-sm">{s.entity_name}</span>
        )}
        <Badge variant="secondary" className="text-[10px]">언급 급증</Badge>
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{s.date}</span>
      </div>
      <div className="text-sm">
        최근 7일 <span className="font-semibold text-up">{p.count_7d ?? "-"}회</span>
        <span className="text-muted-foreground text-xs"> (직전 {p.baseline_7d ?? 0}회)</span>
      </div>
      {p.keywords && p.keywords.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {p.keywords.slice(0, 4).map((k) => (
            <Badge key={k} variant="outline" className="text-[10px] font-normal">{k}</Badge>
          ))}
        </div>
      )}
      {/* 근거 문서 — "왜 이 신호?"는 항상 노출 (신호 노이즈 규율) */}
      {p.docs && p.docs.length > 0 && (
        <ul className="space-y-0.5 border-t pt-1.5">
          {p.docs.slice(0, 2).map((d, i) => (
            <li key={i} className="truncate">
              <a href={d.url} target="_blank" rel="noreferrer" className="text-xs text-muted-foreground hover:text-foreground hover:underline">
                · {d.title}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ---------- Loading skeleton ---------- */

function HomeSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-6 w-24" />
      {[96, 200, 180].map((h, i) => (
        <div key={i} className="border rounded-xl p-4 space-y-3">
          <Skeleton className="h-4 w-32" />
          <Skeleton style={{ height: h }} className="w-full" />
        </div>
      ))}
    </div>
  )
}
