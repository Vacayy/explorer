import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  Bell, Building2, CalendarDays, FileSearch, Home, LineChart, ListChecks,
  MessageCircleQuestion, Newspaper, NotebookPen, Rss, Send, Sparkles, Table2, ScanSearch,
} from "lucide-react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
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
  { label: "종목 발견 — 자연어 검색·전략·기업 조사", to: "/discover", icon: ScanSearch, keywords: "discover screening 스크리닝 전략 시장 분석" },
  { label: "스터디 — 자료를 모아 함께 공부하기", to: "/study", icon: NotebookPen, keywords: "study 스터디 공부 프로젝트" },
  { label: "오늘 — 내 종목 업데이트", to: "/home", icon: Home, keywords: "home stream 홈" },
  { label: "관심목록 — 기업·인물·산업·테마", to: "/follow", icon: Building2, keywords: "follow stocks watchlist 종목 소스" },
  { label: "신호 — 언급 급증·52주 신고가", to: "/explore", icon: LineChart, keywords: "signal" },
  { label: "기업활동 — 유무증·합병·공개매수", to: "/actions", icon: Building2, keywords: "actions 유상증자" },
  { label: "유무증 Pro", to: "/actions?view=pro", icon: Table2, keywords: "rights pro" },
  { label: "문서 검색 — 전체 수집 자료", to: "/feed?view=documents", icon: Newspaper, keywords: "feed 텔레그램 블로그" },
  { label: "소스 관리 — 채널·블로그·유튜브", to: "/sources", icon: Rss, keywords: "source 소스 구독 관리 채널 블로그 유튜브" },
  { label: "Home 피드 — 최신 업데이트", to: "/home?home_view=feed", icon: Newspaper, keywords: "feed 피드 업데이트" },
  { label: "대화 — AI 질문·스레드", to: "/chat", icon: MessageCircleQuestion, keywords: "ask rag chat" },
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
  // 구독 소스 → 소스 도시에 이동 (열려 있을 때만 조회)
  const { data: sources = [] } = useQuery({
    queryKey: ["spine", "sources", "health"],
    queryFn: async () =>
      (await api.get("/api/spine/sources/health")).data.items as
        { kind: string; name: string; key: string }[],
    enabled: open,
    staleTime: 5 * 60_000,
  })

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

  // 지식 주입 (knowledge-system ①) — 문장을 온톨로지에 저장
  const inject = useMutation({
    mutationFn: async (content: string) =>
      (await api.post("/api/spine/knowledge", { content, epistemic: "hypothesis" })).data as
        { title: string; entities: string[] },
    onSuccess: (d) => {
      toast.success(`지식으로 저장 (가설)${d.entities.length ? ` — 연결: ${d.entities.slice(0, 4).join(", ")}` : ""}`)
      setOpen(false)
      setQuery("")
    },
    onError: () => toast.error("저장 실패"),
  })

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
              <CommandItem forceMount value={`discover-${q}`} onSelect={() => go(`/discover?q=${encodeURIComponent(q)}`)}>
                <ScanSearch className="h-3.5 w-3.5" />
                <span>"{q}" 조건으로 종목 찾기</span>
              </CommandItem>
              <CommandItem forceMount value={`search-${q}`} onSelect={() => go(`/feed?q=${encodeURIComponent(q)}`)}>
                <FileSearch className="h-3.5 w-3.5" />
                <span>"{q}" 문서 검색</span>
                <span className="ml-auto text-[10px] text-muted-foreground">의미 기반</span>
              </CommandItem>
              {looksLikeQuestion && (
                <CommandItem forceMount value={`ask-${q}`} onSelect={() => go(`/chat?q=${encodeURIComponent(q)}`)}>
                  <Sparkles className="h-3.5 w-3.5 text-hypothesis" />
                  <span>"{q}" AI에게 질문</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">수집 문서 근거</span>
                </CommandItem>
              )}
              <CommandItem forceMount value={`follow-${q}`} onSelect={() => go(`/feed?industry=${encodeURIComponent(q)}`)}>
                <Bell className="h-3.5 w-3.5" />
                <span>"{q}" 태그 피드 보기</span>
              </CommandItem>
              {q.length >= 8 && (
                <CommandItem forceMount value={`remember-${q}`} onSelect={() => !inject.isPending && inject.mutate(q)}>
                  <NotebookPen className="h-3.5 w-3.5 text-hypothesis" />
                  <span>"{q.length > 40 ? q.slice(0, 40) + "…" : q}" 내 지식으로 저장</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">가설 · 검색·답변에 반영</span>
                </CommandItem>
              )}
            </CommandGroup>
          </>
        )}

        {sources.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="소스 — 관점 프로필">
              {sources.map((s) => (
                <CommandItem
                  key={`${s.kind}:${s.key}`}
                  value={`${s.name} ${s.key} source 소스`}
                  onSelect={() => go(`/source?kind=${s.kind}&key=${encodeURIComponent(s.key)}`)}
                >
                  {s.kind === "telegram" ? <Send className="h-3.5 w-3.5" /> : <Rss className="h-3.5 w-3.5" />}
                  {s.name}
                </CommandItem>
              ))}
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
