import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  Bell, Building2, CalendarDays, FileSearch, Home, LineChart, ListChecks,
  MessageCircleQuestion, Newspaper, Sparkles, Table2,
} from "lucide-react"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator,
} from "@/components/ui/command"

/**
 * 옴니바 (⌘K) — 블룸버그 커맨드라인 패턴. 두 원시 요소(스트림·도시에)를 잇는 유일한 입력.
 * 타이핑 하나로: 종목 → 도시에 / 커맨드 → 화면 / 텍스트 → 문서 검색 / 문장 → AI 질문.
 * additive: 기존 네비를 대체하지 않고 위에 얹는다 (실험 — feat/ux-terminal).
 */

const PAGES = [
  { label: "홈 — 내 종목 업데이트", to: "/home", icon: Home, keywords: "home stream" },
  { label: "신호 — 언급 급증·52주 신고가", to: "/explore", icon: LineChart, keywords: "signal" },
  { label: "기업활동 — 유무증·합병·공개매수", to: "/actions", icon: Building2, keywords: "actions 유상증자" },
  { label: "유무증 Pro", to: "/actions?view=pro", icon: Table2, keywords: "rights pro" },
  { label: "피드 — 전체 수집 문서", to: "/feed", icon: Newspaper, keywords: "feed 텔레그램 블로그" },
  { label: "AI 질문", to: "/ask", icon: MessageCircleQuestion, keywords: "ask rag" },
  { label: "워치리스트", to: "/research/watchlist", icon: ListChecks, keywords: "watchlist" },
  { label: "카탈리스트 캘린더", to: "/research/catalysts", icon: CalendarDays, keywords: "calendar 일정" },
  { label: "VS 비교 (보관함)", to: "/analyze/compare", icon: Table2, keywords: "compare 비교" },
  { label: "투자메모 (보관함)", to: "/research/memos", icon: ListChecks, keywords: "memo 메모" },
  { label: "스크리너 (보관함)", to: "/discover/screener", icon: LineChart, keywords: "screener" },
  { label: "산업군 지도 (보관함)", to: "/discover/industry", icon: Building2, keywords: "industry 밸류체인" },
  { label: "보관함", to: "/archive", icon: Home, keywords: "archive 휴지통" },
] as const

export default function Omnibar() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const navigate = useNavigate()
  const { data: companies = [] } = useCompanySearch(query)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [])

  const go = (to: string) => {
    setOpen(false)
    setQuery("")
    navigate(to)
  }

  const q = query.trim()
  // 문장형이면 AI 질문 후보로 (물음표 또는 어절 3+)
  const looksLikeQuestion = q.endsWith("?") || q.split(/\s+/).length >= 3

  return (
    <CommandDialog open={open} onOpenChange={setOpen} title="옴니바" description="이동·검색·질문">
      <Command shouldFilter={true}>
      <CommandInput
        placeholder="종목·화면 이동, 문서 검색, 질문… (⌘K)"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList className="max-h-[420px]">
        <CommandEmpty>결과 없음 — Enter 대신 아래 검색/질문을 써보세요.</CommandEmpty>

        {/* 종목 → 도시에 */}
        {companies.length > 0 && (
          <CommandGroup heading="종목">
            {companies.slice(0, 5).map((c) => (
              <CommandItem
                key={c.corp_code}
                value={`${c.corp_name} ${c.stock_code ?? ""}`}
                onSelect={() => c.stock_code && go(`/analyze/${c.stock_code}/summary`)}
              >
                <Building2 className="h-3.5 w-3.5" />
                <span className="font-medium">{c.corp_name}</span>
                <span className="ml-auto text-xs text-muted-foreground tabular-nums">{c.stock_code}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {/* 텍스트가 있으면: 검색·질문 액션 (필터 무시하고 항상 표시) */}
        {q.length >= 2 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="검색·질문">
              <CommandItem forceMount value={`search-${q}`} onSelect={() => go(`/feed?q=${encodeURIComponent(q)}`)}>
                <FileSearch className="h-3.5 w-3.5" />
                <span>"{q}" 문서 검색</span>
                <span className="ml-auto text-[10px] text-muted-foreground">의미 기반</span>
              </CommandItem>
              {looksLikeQuestion && (
                <CommandItem forceMount value={`ask-${q}`} onSelect={() => go(`/ask?q=${encodeURIComponent(q)}`)}>
                  <Sparkles className="h-3.5 w-3.5 text-hypothesis" />
                  <span>"{q}" AI에게 질문</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">수집 문서 근거</span>
                </CommandItem>
              )}
              <CommandItem forceMount value={`follow-${q}`} onSelect={() => go(`/feed?industry=${encodeURIComponent(q)}`)}>
                <Bell className="h-3.5 w-3.5" />
                <span>"{q}" 태그 피드 보기</span>
              </CommandItem>
            </CommandGroup>
          </>
        )}

        <CommandSeparator />
        <CommandGroup heading="이동">
          {PAGES.map((p) => (
            <CommandItem key={p.to} value={`${p.label} ${p.keywords}`} onSelect={() => go(p.to)}>
              <p.icon className="h-3.5 w-3.5" />
              {p.label}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
      </Command>
    </CommandDialog>
  )
}
