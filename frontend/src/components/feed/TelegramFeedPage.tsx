import { useState } from "react"
import ReactMarkdown from "react-markdown"
import { HelpCircle, Plus, X, ExternalLink } from "lucide-react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import {
  useTelegramChannels,
  useTelegramFeed,
  useAddTelegramChannel,
  useToggleTelegramChannel,
  type TelegramMessage,
} from "@/hooks/useTelegram"

export default function TelegramFeedPage() {
  const [inputUrl, setInputUrl] = useState("")
  const { data: channels = [], isLoading: chLoading } = useTelegramChannels()
  const {
    data: feed,
    isLoading: feedLoading,
    isError: feedError,
    refetch: refetchFeed,
  } = useTelegramFeed()
  const addChannel = useAddTelegramChannel()

  const messages = feed?.items ?? []
  const hasChannels = channels.length > 0

  const channelDisplayMap = new Map(
    channels.map((ch) => [ch.channel_name, ch.display_name ?? ch.channel_name])
  )

  function handleAdd() {
    const url = inputUrl.trim()
    if (!url) return
    addChannel.mutate(url, {
      onSuccess: () => { setInputUrl(""); toast.success("채널이 추가되었습니다") },
      onError: () => { toast.error("채널을 추가할 수 없습니다. 공개 채널인지 확인해주세요.") },
    })
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-5">
        {/* Channel add bar */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 flex-1">
            <Input
              placeholder="https://t.me/channel_name"
              value={inputUrl}
              onChange={(e) => setInputUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              className="h-9 text-sm max-w-md"
            />
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={addChannel.isPending || !inputUrl.trim()}
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              채널 추가
            </Button>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <button className="text-muted-foreground hover:text-foreground cursor-help">
                <HelpCircle className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="end" className="max-w-xs text-xs leading-relaxed">
              <p className="font-medium mb-1">텔레그램 피드</p>
              <ul className="space-y-0.5 text-muted-foreground list-disc pl-3">
                <li>공개 채널 URL을 입력하면 최신 메시지를 수집합니다</li>
                <li>1시간 간격으로 자동 갱신됩니다</li>
                <li>비공개 채널은 지원하지 않습니다</li>
              </ul>
            </TooltipContent>
          </Tooltip>
        </div>

        {/* No channels */}
        {!chLoading && !hasChannels && (
          <div className="text-center py-20 text-muted-foreground">
            <p className="text-sm">텔레그램 채널을 추가하면 메시지 피드가 표시됩니다</p>
            <p className="text-xs mt-1">예: https://t.me/durov</p>
          </div>
        )}

        {/* Loading */}
        {feedLoading && hasChannels && (
          <div className="columns-1 md:columns-2 lg:columns-3 gap-4 space-y-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Card key={i} className="break-inside-avoid mb-4">
                <CardHeader className="pb-2"><Skeleton className="h-5 w-24" /></CardHeader>
                <CardContent className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-4/5" />
                  <Skeleton className="h-4 w-3/5" />
                  {i % 2 === 0 && <><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-2/3" /></>}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Error */}
        {feedError && (
          <div className="text-center py-12 space-y-3 text-muted-foreground">
            <p className="text-sm">메시지를 불러올 수 없습니다</p>
            <Button variant="outline" size="sm" onClick={() => refetchFeed()}>재시도</Button>
          </div>
        )}

        {/* Pinterest-style masonry */}
        {!feedLoading && !feedError && hasChannels && messages.length > 0 && (
          <div className="columns-1 md:columns-2 lg:columns-3 gap-4">
            {messages.map((msg, idx) => (
              <MessageCard
                key={`${msg.channel_name}-${msg.message_id}-${idx}`}
                msg={msg}
                displayName={channelDisplayMap.get(msg.channel_name)}
              />
            ))}
          </div>
        )}

        {/* Empty */}
        {!feedLoading && !feedError && hasChannels && messages.length === 0 && (
          <div className="text-center py-12 text-muted-foreground">
            <p className="text-sm">메시지가 없습니다</p>
          </div>
        )}
      </div>
    </TooltipProvider>
  )
}

/** Sidebar: subscribed channels with on/off toggle */
export function TelegramChannelsSidebar() {
  const { data: channels = [], isLoading } = useTelegramChannels()
  const toggleChannel = useToggleTelegramChannel()

  if (isLoading) return <div className="px-3 py-4"><Skeleton className="h-4 w-full" /></div>
  if (channels.length === 0) return (
    <div className="px-3 py-8 text-center text-xs text-muted-foreground">구독 채널 없음</div>
  )

  return (
    <div className="py-2">
      <div className="px-3 mb-2">
        <h3 className="text-xs font-semibold text-secondary-foreground">구독 채널</h3>
      </div>
      {channels.map((ch) => {
        const active = ch.is_active === 1
        return (
          <div
            key={ch.id}
            className={cn(
              "flex items-center justify-between px-3 py-2 hover:bg-muted/50 transition-colors",
              !active && "opacity-50"
            )}
          >
            <div className="min-w-0">
              <div className="text-[13px] font-medium truncate">{ch.display_name ?? ch.channel_name}</div>
              <div className="text-[11px] text-muted-foreground">@{ch.channel_name}</div>
            </div>
            <button
              onClick={() => toggleChannel.mutate({ id: ch.id, is_active: !active })}
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
  )
}

function MessageCard({ msg, displayName }: { msg: TelegramMessage; displayName?: string }) {
  const [expanded, setExpanded] = useState(false)

  const dateStr = msg.date
    ? new Date(msg.date).toLocaleDateString("ko-KR", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      })
    : ""

  const content = msg.content || ""
  const isLong = content.length > 500

  return (
    <Card className="break-inside-avoid mb-4 transition-all duration-150 hover:shadow-md hover:-translate-y-0.5">
      <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
        <Badge variant="secondary" className="text-xs font-medium">
          {displayName ?? msg.channel_name}
        </Badge>
        {dateStr && <span className="text-[11px] text-muted-foreground">{dateStr}</span>}
      </CardHeader>
      <CardContent className="space-y-2">
        <div className={`text-sm leading-relaxed ${!expanded && isLong ? "max-h-[500px] overflow-hidden relative" : ""}`}>
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer" className="text-[#0071e3] hover:underline break-all">
                  {children}
                </a>
              ),
              strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
              em: ({ children }) => <em className="italic">{children}</em>,
              ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>,
              li: ({ children }) => <li>{children}</li>,
              code: ({ children }) => <code className="bg-muted px-1 py-0.5 rounded text-xs font-mono">{children}</code>,
              blockquote: ({ children }) => <blockquote className="border-l-2 border-primary/30 pl-3 text-muted-foreground italic">{children}</blockquote>,
            }}
          >
            {linkifyText(preserveNewlines(content))}
          </ReactMarkdown>
          {!expanded && isLong && (
            <div className="absolute bottom-0 left-0 right-0 h-20 bg-gradient-to-t from-card to-transparent" />
          )}
        </div>
        <div className="flex items-center justify-between pt-1">
          {isLong && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-primary hover:underline"
            >
              {expanded ? "접기" : "더 보기"}
            </button>
          )}
          {msg.link && (
            <a
              href={msg.link}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-muted-foreground hover:text-primary inline-flex items-center gap-1 ml-auto"
            >
              원문 <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/** Preserve newlines for ReactMarkdown: keep double newlines as paragraph breaks,
    convert single newlines to markdown line breaks (two trailing spaces + newline) */
function preserveNewlines(text: string): string {
  return text.replace(/\n{2,}/g, "\n\n").replace(/(?<!\n)\n(?!\n)/g, "  \n")
}

/** Convert plain URLs to markdown links */
function linkifyText(text: string): string {
  return text.replace(
    /(https?:\/\/[^\s<>)\]]+)/g,
    (url) => `[${url.length > 60 ? url.slice(0, 57) + "..." : url}](${url})`
  )
}
