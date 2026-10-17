import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { WidgetHero, WidgetState } from "@/components/shared/WidgetFrame"
import { ACT_META, actLink } from "@/components/home/AiActivityFeed"
import { DocumentCard } from "@/components/feed/FeedPost"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { useProjects } from "@/components/study/useProjects"
import { AI_ACTIVITY, useAiActivity } from "@/hooks/useAiActivity"
import { useFeedTopics } from "@/hooks/useFeedTopics"
import { useTimeline, useTimelineChannels } from "@/hooks/useTimeline"
import { aiCoverageLabel, groupDirectory } from "@/lib/canvas"
import { formatKstDateTime, formatNumber, formatRelativeTime } from "@/utils/format"
import type { WidgetBodyProps, WidgetDef, WidgetMeta } from "./types"

/**
 * 캔버스 위젯 4종 — 요약층만 (docs/specs/home-widgets.md §2, docs/specs/canvas.md §3). 모두 캐시된 GET 훅만 읽는다.
 * 기준 시각은 원천 시각(최신 게시물·생성물·신호 날짜·프로젝트 갱신)이다.
 */

const FEED = "/home?home_view=feed"
const PLATFORM: Record<string, string> = { telegram: "텔레그램", blog: "블로그", youtube: "유튜브" }
const newest = (xs: (string | null | undefined)[]) => xs.filter(Boolean).sort().at(-1) ?? null

/* ── 피드 — 팔로우한 소스의 최신 글 (읽음 표시는 안 한다: 위젯은 GET만) ── */
const FEED_QUERY = { scope: "sources", kind: "all", source: "all", page: 1 } as const
function useFeedMeta(): WidgetMeta {
  const q = useTimeline(FEED_QUERY)
  const latest = q.data?.items[0]?.occurred_at
  return { asOf: latest ? formatKstDateTime(latest) : null }
}
const FEED_TABS = [{ value: "all", label: "전체" }, { value: "telegram", label: "텔레그램" }, { value: "blog", label: "블로그" }, { value: "youtube", label: "유튜브" }]
function FeedBody({ h }: WidgetBodyProps) {
  // 출처 탭은 URL(feed_src)이 단일 소스 — 새로고침·뒤로 가기에도 유지
  const [params, setParams] = useSearchParams()
  const requested = params.get("feed_src") ?? "all"
  const source = FEED_TABS.some(t => t.value === requested) ? requested : "all"
  const setSource = (v: string) => setParams(prev => { const next = new URLSearchParams(prev); if (v === "all") next.delete("feed_src"); else next.set("feed_src", v); return next }, { replace: true, preventScrollReset: true })
  return <div className="flex h-full flex-col gap-2">
    <SegmentTabs tabs={FEED_TABS} value={source} onChange={setSource} />
    <div className="min-h-0 flex-1"><FeedList h={h} source={source} /></div>
  </div>
}
function FeedList({ h, source }: { h: number; source: string }) {
  const q = useTimeline({ ...FEED_QUERY, source })
  const navigate = useNavigate()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const docs = q.data.items.filter(i => i.document)
  if (!docs.length) return <WidgetState empty emptyText={source === "all" ? "팔로우한 소스의 글이 아직 없어요. 캔버스 › 소스에서 등록합니다." : "이 출처의 최신 글이 없어요."} />
  // 작게 줄이면 제목만, 넉넉하면 피드와 같은 게시물 행(요약 보기)을 위젯 안에서 스크롤
  if (h <= 3) return <ul className="divide-y overflow-hidden text-[13px]">
    {docs.slice(0, Math.max(1, h * 2 - 1)).map(i => (
      <li key={i.id}><Link to={`/doc/${i.document!.id}`} className="flex items-center gap-2 py-1.5 hover:underline">
        <span className="min-w-0 flex-1 truncate">{i.document!.title || i.title}</span>
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatRelativeTime(i.occurred_at)}</span>
      </Link></li>
    ))}
  </ul>
  return <div className="-mr-2 h-full overflow-y-auto pr-2">
    {docs.map(i => <DocumentCard key={i.id} doc={i.document!} variant="row" timeLabel={i.time_label} reading="summary"
      onChipFilter={tag => navigate(`/feed?view=documents&q=${encodeURIComponent(tag.name)}`)} />)}
    <Button asChild variant="ghost" size="sm" className="mt-2 w-full"><Link to={source === "all" ? FEED : `${FEED}&channel_type=${source}`}>피드에서 더 보기</Link></Button>
  </div>
}

/* ── 안 읽은 소스 ── */
function useUnreadMeta(): WidgetMeta {
  const q = useTimelineChannels()
  const human = q.data ? groupDirectory(q.data.items).human : []
  const latest = newest(human.map(i => i.latest_at))
  return { asOf: latest ? formatKstDateTime(latest) : null }
}
function UnreadBody({ h }: WidgetBodyProps) {
  const q = useTimelineChannels()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  const human = groupDirectory(q.data.items).human
  const unread = human.filter(i => i.unread > 0).sort((a, b) => b.unread - a.unread)
  if (!human.length) return <WidgetState empty emptyText="팔로우한 소스가 아직 없어요. 캔버스 › 소스에서 등록합니다." />
  if (!unread.length) return <WidgetState empty emptyText="팔로우한 소스를 모두 읽었어요." />
  const total = unread.reduce((n, i) => n + i.unread, 0)
  return <div className="flex h-full flex-col gap-2">
    <WidgetHero value={formatNumber(total)} aside={<span className="text-sm text-muted-foreground">안 읽음 · 소스 {formatNumber(unread.length)}곳</span>} />
    {h > 2 && <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {unread.slice(0, Math.max(1, h * 2 - 3)).map(i => (
        <li key={i.id}>
          <Link to={`${FEED}&channel=${encodeURIComponent(i.id)}`} className="flex items-center gap-2 py-1.5 hover:underline">
            <span className="min-w-0 flex-1 truncate">{i.name}</span>
            <span className="shrink-0 text-[11px] text-muted-foreground">{PLATFORM[i.platform]}</span>
            <Badge variant="secondary" className="shrink-0 tabular-nums">{formatNumber(i.unread)}</Badge>
          </Link>
        </li>
      ))}
    </ul>}
  </div>
}

/* ── AI가 최근 만든 것 ── */
function useAiMeta(): WidgetMeta {
  const q = useAiActivity()
  const latest = newest((q.data ?? []).map(a => a.created_at))
  return { asOf: latest ? formatKstDateTime(latest) : null }
}
function AiBody({ h }: WidgetBodyProps) {
  const q = useAiActivity()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!q.data.length) return <WidgetState empty emptyText={`지난 ${AI_ACTIVITY.days}일간 자동생성된 콘텐츠가 없어요.`} />
  const coverage = aiCoverageLabel(q.data.map(a => a.created_at), AI_ACTIVITY.limit, AI_ACTIVITY.days, formatKstDateTime)
  return <div className="flex h-full flex-col gap-2">
    <p className="text-[12px] text-muted-foreground">{coverage}</p>
    <ul className="min-h-0 divide-y overflow-hidden text-[13px]">
      {q.data.slice(0, Math.max(1, Math.round((h - 1) * 2.2))).map((a, n) => {
        const m = ACT_META[a.type] ?? ACT_META.narrative
        return <li key={`${a.type}-${a.topic}-${n}`}>
          <Link to={actLink(a)} className="flex items-center gap-2 py-1.5 hover:underline">
            <Badge variant="outline" className={`shrink-0 text-[11px] ${m.cls}`}>{m.label}</Badge>
            <span className="min-w-0 flex-1 truncate">{a.title}</span>
            <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatRelativeTime(a.created_at.includes("T") ? a.created_at : `${a.created_at.replace(" ", "T")}Z`)}</span>
          </Link>
        </li>
      })}
    </ul>
  </div>
}

/* ── 오늘의 주제 ── */
function useTopicsMeta(): WidgetMeta {
  return { asOf: useFeedTopics().asOf }
}
function TopicsBody({ h }: WidgetBodyProps) {
  const t = useFeedTopics()
  if (t.isLoading) return <WidgetState loading />
  if (t.isError) return <WidgetState error onRetry={t.refetch} />
  const groups = [{ label: "주목 주제", names: t.themes }, { label: "부상 종목", names: t.stocks }].filter(g => g.names.length)
  if (!groups.length) return <WidgetState empty emptyText="최근 주목 주제·부상 종목 신호가 없어요." />
  return <div className="flex h-full flex-col gap-1.5 overflow-hidden">
    {groups.slice(0, h <= 2 ? 1 : 2).map(g => (
      <div key={g.label} className="flex flex-wrap items-center gap-1">
        <span className="w-14 shrink-0 text-[11px] text-muted-foreground">{g.label}</span>
        {g.names.map(name => (
          <Button key={name} asChild variant="outline" size="sm" className="h-6 px-2 text-[12px] font-normal">
            <Link to={`${FEED}&reader_topic=${encodeURIComponent(name)}`}>{name}</Link>
          </Button>
        ))}
      </div>
    ))}
  </div>
}

/* ── 이어서 공부하기 ── */
function useStudyMeta(): WidgetMeta {
  const q = useProjects()
  const latest = newest((q.data ?? []).map(p => p.updated_at))
  return { asOf: latest ? formatKstDateTime(latest) : null }
}
function StudyBody({ h }: WidgetBodyProps) {
  const q = useProjects()
  if (!q.data) return <WidgetState loading={q.isLoading} error={q.isError} onRetry={() => void q.refetch()} />
  if (!q.data.length) return <WidgetState empty emptyText="스터디 프로젝트가 아직 없어요. 문서에서 '스터디에 추가'로 시작합니다." />
  const recent = [...q.data].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, h <= 2 ? 3 : 3 + (h - 2) * 2)
  return <ul className="divide-y overflow-hidden text-[13px]">
    {recent.map(p => (
      <li key={p.id}>
        <Link to={`/study/projects/${p.id}`} className="flex items-center gap-2 py-1 hover:underline">
          <span className="min-w-0 flex-1 truncate">{p.title}</span>
          <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">자료 {formatNumber(p.document_count ?? p.documents?.length ?? 0)}</span>
        </Link>
      </li>
    ))}
  </ul>
}

/** 캔버스 위젯 — registry.tsx가 이 배열을 그대로 펼친다 */
export const CANVAS_WIDGETS: WidgetDef[] = [
  { id: "canvas.feed", title: "피드", description: "팔로우한 텔레그램·블로그·유튜브의 최신 글 — 요약으로 훑기", section: "canvas", group: "피드",
    size: { w: 6, h: 9, minW: 3, minH: 2 }, detailPath: FEED, useMeta: useFeedMeta, Body: FeedBody },
  { id: "canvas.unread", title: "안 읽은 소스", description: "팔로우한 텔레그램·블로그·유튜브 중 안 읽은 글이 많은 곳", section: "canvas", group: "피드",
    size: { w: 4, h: 3, minW: 3, minH: 2 }, detailPath: FEED, useMeta: useUnreadMeta, Body: UnreadBody },
  { id: "canvas.ai", title: "AI가 최근 만든 것", description: "내러티브·종목 요약·유튜브 정리본 등 최신 생성물", section: "canvas", group: "피드",
    size: { w: 4, h: 4, minW: 3, minH: 2 }, detailPath: FEED, useMeta: useAiMeta, Body: AiBody },
  { id: "canvas.topics", title: "오늘의 주제", description: "주목 주제·부상 종목 — 누르면 피드를 그 주제로", section: "canvas", group: "피드",
    size: { w: 4, h: 2, minW: 3, minH: 2 }, detailPath: FEED, useMeta: useTopicsMeta, Body: TopicsBody },
  { id: "canvas.study", title: "이어서 공부하기", description: "최근에 손댄 스터디 프로젝트", section: "canvas", group: "스터디",
    size: { w: 4, h: 2, minW: 3, minH: 2 }, detailPath: "/study", useMeta: useStudyMeta, Body: StudyBody },
]
