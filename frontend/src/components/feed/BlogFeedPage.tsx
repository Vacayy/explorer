import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { HelpCircle, Plus, ExternalLink, X } from "lucide-react"
import { toast } from "sonner"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import api from "@/api/client"
import {
  useBlogSources,
  useBlogFeed,
  useBlogTags,
  useBlogPost,
  useAddBlogSource,
  useToggleBlogSource,
  type BlogPost,
} from "@/hooks/useBlogFeed"

export default function BlogFeedPage() {
  const [inputUrl, setInputUrl] = useState("")
  const [activeTag, setActiveTag] = useState<string | undefined>(undefined)
  // Browser-like tab state
  const [openTabs, setOpenTabs] = useState<{ id: number; title: string }[]>([])
  const [activeTabId, setActiveTabId] = useState<number | null>(null)

  function openPost(id: number, title: string) {
    if (!openTabs.find((t) => t.id === id)) {
      setOpenTabs((prev) => [...prev, { id, title }])
    }
    setActiveTabId(id)
  }
  function closeTab(id: number) {
    setOpenTabs((prev) => {
      const next = prev.filter((t) => t.id !== id)
      if (activeTabId === id) setActiveTabId(next.length > 0 ? next[next.length - 1].id : null)
      return next
    })
  }
  function closeAllTabs() {
    setOpenTabs([])
    setActiveTabId(null)
  }

  const { data: sources = [], isLoading: sourcesLoading } = useBlogSources()
  const {
    data: feed,
    isLoading: feedLoading,
    isError: feedError,
    refetch: refetchFeed,
  } = useBlogFeed(activeTag)
  const addSource = useAddBlogSource()

  const posts = feed?.items ?? []
  const hasSources = sources.length > 0

  function handleAdd() {
    const url = inputUrl.trim()
    if (!url) return
    addSource.mutate(url, {
      onSuccess: () => { setInputUrl(""); toast.success("블로그가 추가되었습니다") },
      onError: (err) => { toast.error(err.message || "블로그를 추가할 수 없습니다") },
    })
  }

  // Group posts by time bucket
  const grouped = groupByTime(posts)

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-5">
        {/* URL input bar */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 flex-1">
            <Input
              placeholder="https://example.tistory.com 또는 RSS URL"
              value={inputUrl}
              onChange={(e) => setInputUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              className="h-9 text-sm max-w-md"
            />
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={addSource.isPending || !inputUrl.trim()}
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              블로그 추가
            </Button>
          </div>
          {activeTag && (
            <Badge variant="secondary" className="gap-1 cursor-pointer" onClick={() => setActiveTag(undefined)}>
              {activeTag} <X className="w-3 h-3" />
            </Badge>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <button className="text-muted-foreground hover:text-foreground cursor-help">
                <HelpCircle className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="end" className="max-w-xs text-xs leading-relaxed">
              <p className="font-medium mb-1">블로그 피드</p>
              <ul className="space-y-0.5 text-muted-foreground list-disc pl-3">
                <li>Tistory, 네이버 블로그 URL을 지원합니다</li>
                <li>RSS를 제공하는 모든 블로그를 추가할 수 있습니다</li>
                <li>1시간 간격으로 자동 갱신됩니다</li>
              </ul>
            </TooltipContent>
          </Tooltip>
        </div>

        {/* No sources */}
        {!sourcesLoading && !hasSources && (
          <div className="text-center py-20 text-muted-foreground">
            <p className="text-sm">블로그를 추가하면 최신 포스트가 표시됩니다</p>
            <p className="text-xs mt-1">예: https://stock-factory.tistory.com</p>
          </div>
        )}

        {/* Loading skeleton */}
        {feedLoading && hasSources && (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Card key={i}>
                <CardContent className="py-3 px-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-4 w-3/4" />
                      <Skeleton className="h-3 w-full" />
                      <Skeleton className="h-3 w-1/2" />
                    </div>
                    <Skeleton className="h-3 w-16 shrink-0" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Error */}
        {feedError && (
          <div className="text-center py-12 space-y-3 text-muted-foreground">
            <p className="text-sm">포스트를 불러올 수 없습니다</p>
            <Button variant="outline" size="sm" onClick={() => refetchFeed()}>재시도</Button>
          </div>
        )}

        {/* List view with time grouping */}
        {!feedLoading && !feedError && hasSources && posts.length > 0 && (
          <div className="space-y-6">
            {grouped.map(({ label, items }) => (
              <div key={label}>
                <h2 className="text-xs font-semibold text-muted-foreground mb-2 px-1">{label}</h2>
                <div className="space-y-2">
                  {items.map((post) => {
                    const dateStr = post.published_at
                      ? formatDate(post.published_at)
                      : post.fetched_at
                      ? formatDate(post.fetched_at)
                      : ""
                    return (
                      <Card
                        key={post.id}
                        className="cursor-pointer transition-all duration-150 hover:shadow-md hover:-translate-y-0.5"
                        onClick={() => openPost(post.id, post.title)}
                      >
                        <CardContent className="py-3 px-4">
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0 flex-1">
                              <h3 className="text-sm font-semibold leading-snug line-clamp-1">{post.title}</h3>
                              {post.summary && (
                                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{post.summary}</p>
                              )}
                              <div className="flex items-center gap-2 mt-2 flex-wrap">
                                <Badge variant="secondary" className="text-[10px]">{post.blog_name || post.platform}</Badge>
                                {post.author && <span className="text-[10px] text-muted-foreground">by {post.author}</span>}
                                {post.tags?.map((tag) => (
                                  <Badge
                                    key={`${tag.type}-${tag.value}`}
                                    variant="outline"
                                    className="text-[10px] cursor-pointer hover:bg-accent"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setActiveTag(activeTag === tag.value ? undefined : tag.value)
                                    }}
                                  >
                                    {tag.value}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                            <span className="text-[11px] text-muted-foreground whitespace-nowrap shrink-0">{dateStr}</span>
                          </div>
                        </CardContent>
                      </Card>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty */}
        {!feedLoading && !feedError && hasSources && posts.length === 0 && (
          <div className="text-center py-12 text-muted-foreground">
            <p className="text-sm">{activeTag ? `'${activeTag}' 태그의 포스트가 없습니다` : "포스트가 없습니다"}</p>
          </div>
        )}

        {/* Browser-like reader with tabs */}
        <PostBrowser
          tabs={openTabs}
          activeTabId={activeTabId}
          onSelectTab={setActiveTabId}
          onCloseTab={closeTab}
          onClose={closeAllTabs}
        />
      </div>
    </TooltipProvider>
  )
}

/** Sidebar: blog sources with on/off toggle + tag filter */
export function BlogSourcesSidebar() {
  const { data: sources = [], isLoading: sourcesLoading } = useBlogSources()
  const { data: tags = [] } = useBlogTags()
  const toggleSource = useToggleBlogSource()
  const [activeTag, setActiveTag] = useState<string | undefined>(undefined)
  const qc = useQueryClient()
  const addBlog = useMutation({
    mutationFn: async (url: string) =>
      (await api.post("/api/spine/sources/blog", { url })).data as { url: string; blog_name: string | null },
    onSuccess: (d) => {
      toast.success(`'${d.blog_name || d.url}' 등록 — 백그라운드 수집 시작`)
      qc.invalidateQueries({ queryKey: ["blog-sources"] })
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? "블로그 등록 실패")
    },
  })

  const industryTags = tags.filter((t) => t.tag_type === "industry")
  const topicTags = tags.filter((t) => t.tag_type === "topic")

  if (sourcesLoading) return <div className="px-3 py-4"><Skeleton className="h-4 w-full" /></div>

  return (
    <div className="py-2 space-y-4">
      {/* Sources */}
      <div>
        <div className="px-3 mb-2">
          <h3 className="text-xs font-semibold text-secondary-foreground">구독 블로그</h3>
        </div>
        <form
          className="px-3 pb-2 flex gap-1"
          onSubmit={(e) => {
            e.preventDefault()
            const v = new FormData(e.currentTarget).get("v")?.toString().trim()
            if (v) { addBlog.mutate(v); (e.target as HTMLFormElement).reset() }
          }}
        >
          <input name="v" placeholder="블로그 URL (네이버/티스토리/RSS)" disabled={addBlog.isPending}
            className="min-w-0 flex-1 h-7 rounded-md border bg-background px-2 text-[11px] outline-none focus:ring-1 focus:ring-ring" />
          <button type="submit" disabled={addBlog.isPending}
            className="shrink-0 h-7 px-2 rounded-md bg-primary text-primary-foreground text-[11px] disabled:opacity-50">
            {addBlog.isPending ? "…" : "추가"}
          </button>
        </form>
        {sources.length === 0 && (
          <div className="px-3 py-4 text-center text-xs text-muted-foreground">구독 블로그 없음</div>
        )}
        {sources.map((src) => {
          const active = src.is_active === 1
          return (
            <div
              key={src.id}
              className={cn(
                "flex items-center justify-between px-3 py-2 hover:bg-muted/50 transition-colors",
                !active && "opacity-50"
              )}
            >
              <div className="min-w-0">
                <div className="text-[13px] font-medium truncate">{src.blog_name || src.url}</div>
                <div className="text-[11px] text-muted-foreground">{src.author ?? src.platform}</div>
              </div>
              <button
                onClick={() => toggleSource.mutate({ id: src.id, is_active: !active })}
                className={cn(
                  "shrink-0 ml-2 w-5 h-5 rounded-full border-2 transition-colors flex items-center justify-center",
                  active
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-muted-foreground/30 bg-transparent"
                )}
                title={active ? "피드에서 숨기기" : "피드에 표시"}
              >
                {active && <span className="text-[10px]">✓</span>}
              </button>
            </div>
          )
        })}
      </div>

      {/* Industry tags */}
      {industryTags.length > 0 && (
        <div>
          <div className="px-3 mb-2">
            <h3 className="text-xs font-semibold text-secondary-foreground">산업</h3>
          </div>
          <div className="px-3 flex flex-wrap gap-1.5">
            {industryTags.map((t) => (
              <Badge
                key={t.tag_value}
                variant={activeTag === t.tag_value ? "default" : "outline"}
                className="text-[10px] cursor-pointer hover:bg-accent"
                onClick={() => setActiveTag(activeTag === t.tag_value ? undefined : t.tag_value)}
              >
                {t.tag_value}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Topic tags */}
      {topicTags.length > 0 && (
        <div>
          <div className="px-3 mb-2">
            <h3 className="text-xs font-semibold text-secondary-foreground">주제</h3>
          </div>
          <div className="px-3 flex flex-wrap gap-1.5">
            {topicTags.map((t) => (
              <Badge
                key={t.tag_value}
                variant={activeTag === t.tag_value ? "default" : "outline"}
                className="text-[10px] cursor-pointer hover:bg-accent"
                onClick={() => setActiveTag(activeTag === t.tag_value ? undefined : t.tag_value)}
              >
                {t.tag_value}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/** Browser-like overlay reader with tabs */
function PostBrowser({ tabs, activeTabId, onSelectTab, onCloseTab, onClose }: {
  tabs: { id: number; title: string }[]
  activeTabId: number | null
  onSelectTab: (id: number) => void
  onCloseTab: (id: number) => void
  onClose: () => void
}) {
  const activePost = useBlogPost(activeTabId)
  const post = activePost.data
  const dateStr = post?.published_at ? formatDate(post.published_at) : ""

  if (tabs.length === 0) return null

  return (
    <Dialog open={tabs.length > 0} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-[95vw] w-[95vw] h-[90vh] p-0 flex flex-col gap-0 overflow-hidden rounded-xl">
        {/* Browser-like tab bar */}
        <div className="flex items-center bg-muted/50 border-b px-2 pt-2 gap-0.5 overflow-x-auto shrink-0">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-t-lg max-w-[200px] cursor-pointer transition-colors",
                tab.id === activeTabId
                  ? "bg-card border border-b-0 text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )}
              onClick={() => onSelectTab(tab.id)}
            >
              <span className="truncate">{tab.title}</span>
              <button
                onClick={(e) => { e.stopPropagation(); onCloseTab(tab.id) }}
                className="shrink-0 hover:text-destructive"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto">
          {activePost.isLoading && (
            <div className="space-y-3 p-8">
              <Skeleton className="h-7 w-3/4" />
              <Skeleton className="h-4 w-1/3" />
              <div className="space-y-2 mt-6">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            </div>
          )}
          {post && (
            <article className="max-w-4xl mx-auto px-8 py-6">
              <DialogHeader className="mb-6">
                <DialogTitle className="text-xl leading-snug">{post.title}</DialogTitle>
                <div className="flex items-center gap-2 text-sm text-muted-foreground mt-2">
                  {post.blog_name && <Badge variant="secondary" className="text-xs">{post.blog_name}</Badge>}
                  {post.author && <span>by {post.author}</span>}
                  {dateStr && <span>· {dateStr}</span>}
                </div>
              </DialogHeader>
              <Separator className="mb-6" />
              {post.content ? (
                <div
                  className="prose prose-sm max-w-none
                    prose-p:mb-3 prose-p:leading-relaxed
                    prose-a:text-[#0071e3] prose-a:no-underline hover:prose-a:underline
                    prose-img:rounded-lg prose-img:max-w-full
                    prose-headings:mt-6 prose-headings:mb-3
                    prose-blockquote:border-l-primary/30 prose-blockquote:text-muted-foreground
                    prose-code:bg-muted prose-code:px-1 prose-code:rounded prose-code:text-xs
                    prose-li:mb-1"
                  dangerouslySetInnerHTML={{ __html: post.content }}
                />
              ) : (
                <p className="text-sm text-muted-foreground py-8 text-center">본문을 불러올 수 없습니다.</p>
              )}
              {post.url && (
                <div className="mt-8 pt-4 border-t">
                  <a
                    href={post.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-primary inline-flex items-center gap-1 hover:underline"
                  >
                    원문에서 보기 <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>
              )}
            </article>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString("ko-KR", {
      year: "numeric", month: "2-digit", day: "2-digit",
    })
  } catch {
    return dateStr
  }
}

function groupByTime(posts: BlogPost[]): { label: string; items: BlogPost[] }[] {
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const weekStart = new Date(todayStart)
  weekStart.setDate(weekStart.getDate() - 7)

  const today: BlogPost[] = []
  const thisWeek: BlogPost[] = []
  const older: BlogPost[] = []

  for (const post of posts) {
    const dateStr = post.published_at || post.fetched_at
    const date = dateStr ? new Date(dateStr) : null
    if (!date || isNaN(date.getTime())) {
      older.push(post)
    } else if (date >= todayStart) {
      today.push(post)
    } else if (date >= weekStart) {
      thisWeek.push(post)
    } else {
      older.push(post)
    }
  }

  const result: { label: string; items: BlogPost[] }[] = []
  if (today.length > 0) result.push({ label: "오늘", items: today })
  if (thisWeek.length > 0) result.push({ label: "이번 주", items: thisWeek })
  if (older.length > 0) result.push({ label: "이전", items: older })
  return result
}
