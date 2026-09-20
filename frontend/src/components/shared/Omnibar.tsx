import { useEffect, useMemo, useState, type ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import {
  ArrowLeft, BookOpen, Building2, CornerDownLeft, FileSearch, FolderPlus, Globe, Home, LineChart, MessageCircleQuestion,
  NotebookPen, ScanSearch, Sparkles, Table2, Tag, User, Layers,
} from "lucide-react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { useAddMember, useGroups } from "@/hooks/useGroups"
import { readRecentStocks, rememberRecentStock } from "@/lib/recentStocks"
import { formatKrw, formatNumber, formatPercent } from "@/utils/format"
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator,
} from "@/components/ui/command"

/**
 * 옴니바 (⌘K · /) — 종목·티커·인물·화면·문장을 한 입력으로 잇는다. D-189.
 * 검색과 순위는 서버(`/api/spine/search`)가 정하고 여기서는 cmdk의 자체 필터를 끈다(shouldFilter=false).
 * 빈 상태는 "돌아갈 곳"(최근 본 종목·오늘 켜진 신호·핀 이동), 종목 행에서 Tab은 그 종목에 대한 행동을 펼친다.
 */

interface SearchCompany { stock_code: string; name: string; market: string | null; sector: string | null; close: number | null; change_pct: number | null; market_cap: number | null; in_groups: string[] }
interface SearchResponse {
  query: string
  companies: SearchCompany[]
  us: { ticker: string; name: string; group_label: string | null }[]
  entities: { id: number; type: string; name: string }[]
  groups: { id: number; name: string; kind: string; member_count: number }[]
  projects: { id: number; title: string }[]
}
interface TodaySignal { stock_code: string; name: string; label: string; group_id: number; group_name: string; as_of: string }

const PAGES = [
  { label: "종목 발견", hint: "자연어 검색·전략·기업 조사", to: "/discover", icon: ScanSearch, keywords: "discover screening 스크리닝 전략 시장 분석 검색", pinned: true },
  { label: "종목 묶음", hint: "포트폴리오·관심 종목 감시", to: "/follow/stocks", icon: Layers, keywords: "portfolio watch 묶음 감시 관심 종목 포트폴리오", pinned: true },
  { label: "스터디", hint: "자료를 모아 함께 공부하기", to: "/study", icon: NotebookPen, keywords: "study 스터디 공부 프로젝트", pinned: true },
  { label: "대화", hint: "AI 질문·스레드", to: "/chat", icon: MessageCircleQuestion, keywords: "ask rag chat 대화 질문", pinned: true },
  { label: "Home", hint: "시장 브리핑·피드", to: "/home", icon: Home, keywords: "home stream 홈 브리핑", pinned: true },
  { label: "월드모델", hint: "내러티브·지식", to: "/narrative", icon: Globe, keywords: "narrative worldmodel 월드모델 내러티브 지식", pinned: true },
  { label: "관심목록", hint: "기업·인물·산업·테마", to: "/follow", icon: Building2, keywords: "follow watchlist 관심목록 팔로우" },
  { label: "신호", hint: "언급 급증·52주 신고가", to: "/explore", icon: LineChart, keywords: "signal 신호" },
  { label: "기업활동", hint: "유무증·합병·공개매수", to: "/actions", icon: Building2, keywords: "actions 유상증자 기업활동" },
  { label: "문서 검색", hint: "전체 수집 자료", to: "/feed?view=documents", icon: FileSearch, keywords: "feed documents 문서 텔레그램 블로그" },
  { label: "소스 관리", hint: "채널·블로그·유튜브", to: "/sources", icon: Globe, keywords: "source 소스 구독 관리 채널 블로그 유튜브" },
  { label: "미국 종목", hint: "도시에·컨콜", to: "/us", icon: Globe, keywords: "us 미국 컨콜 transcript" },
  { label: "카탈리스트 캘린더", hint: "", to: "/research/catalysts", icon: LineChart, keywords: "calendar 일정 카탈리스트" },
  { label: "보관함", hint: "예전 화면", to: "/archive", icon: Home, keywords: "archive 보관함 스크리너 비교 메모 산업군" },
] as const

type Intent = "empty" | "code" | "ticker" | "name" | "sentence"

/** 입력 형태로 의도를 정한다. 판별이 틀려도 다른 그룹은 그대로 보이므로 값싸게 틀려도 된다. */
function classify(q: string): Intent {
  if (!q) return "empty"
  if (/^\d{6}$/.test(q)) return "code"
  if (/^[A-Z][A-Z0-9.\-]{0,5}$/.test(q)) return "ticker"
  if (/(찾아줘|추려줘|골라줘|보여줘|알려줘|뭐야|왜|어때|\?)$/.test(q) || q.split(/\s+/).length >= 3) return "sentence"
  return "name"
}
/** 문장의 기본 행동: "찾아줘"류·종목 언급은 발견, 질문형은 대화. */
function discoverFirst(q: string): boolean {
  if (/(찾아줘|추려줘|골라줘|스크리닝|종목|조건)/.test(q)) return true
  return !/(\?|알려줘|뭐야|왜|어때|어떻게)$/.test(q)
}
const INTENT_LABEL: Record<Intent, string> = { empty: "", code: "종목 코드", ticker: "미국 티커", name: "이름", sentence: "문장" }

function Highlight({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>
  const index = text.toLowerCase().indexOf(q.toLowerCase())
  if (index < 0) return <>{text}</>
  return <>{text.slice(0, index)}<mark className="rounded-sm bg-primary/15 text-inherit">{text.slice(index, index + q.length)}</mark>{text.slice(index + q.length)}</>
}

function Row({ icon, title, sub, right, className = "" }: { icon: ReactNode; title: ReactNode; sub?: ReactNode; right?: ReactNode; className?: string }) {
  return <div className={`flex w-full min-w-0 items-center gap-3 ${className}`}>
    <span className="flex size-5 shrink-0 items-center justify-center text-muted-foreground">{icon}</span>
    <span className="flex min-w-0 flex-1 flex-col"><span className="truncate font-medium">{title}</span>{sub && <span className="truncate text-caption text-muted-foreground">{sub}</span>}</span>
    {right && <span className="shrink-0 text-right text-caption tabular-nums text-muted-foreground">{right}</span>}
  </div>
}

type Focus = { code: string; name: string; market: "kr" | "us" }

export default function Omnibar() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [focus, setFocus] = useState<Focus | null>(null)
  const [highlighted, setHighlighted] = useState("")
  const navigate = useNavigate()
  const q = query.trim()
  const intent = classify(q)
  const search = useQuery({
    queryKey: ["spine", "search", q],
    queryFn: async () => (await api.get<SearchResponse>("/api/spine/search", { params: { q, limit: 20 } })).data,
    enabled: open && q.length >= 1 && !focus,
    staleTime: 30_000,
    placeholderData: previous => previous,
  })
  const today = useQuery({ queryKey: ["spine", "search", "today"], queryFn: async () => (await api.get<{ items: TodaySignal[]; as_of: string | null }>("/api/spine/search/today")).data, enabled: open && !q, staleTime: 60_000 })
  const groups = useGroups()
  const addMember = useAddMember()
  const recent = useMemo(() => open ? readRecentStocks() : [], [open])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setOpen(v => !v) }
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [])
  useEffect(() => { if (!open) { setQuery(""); setFocus(null); setShowAll(false) } }, [open])

  const go = (to: string) => { setOpen(false); navigate(to) }
  const openCompany = (company: { code: string; name: string; market: "kr" | "us" }, path?: string) => {
    rememberRecentStock(company)
    go(path ?? (company.market === "us" ? `/us/${company.code}` : `/analyze/${company.code}/summary`))
  }
  const inject = useMutation({
    mutationFn: async (content: string) => (await api.post("/api/spine/knowledge", { content, epistemic: "hypothesis" })).data as { entities: string[] },
    onSuccess: d => { toast.success(`지식으로 저장 (가설)${d.entities.length ? ` — 연결: ${d.entities.slice(0, 4).join(", ")}` : ""}`); setOpen(false) },
    onError: () => toast.error("저장 실패"),
  })

  // Tab on a highlighted stock row opens its actions; ← or Backspace on an empty query goes back.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (focus) {
      if (e.key === "ArrowLeft" || (e.key === "Backspace" && !query)) { e.preventDefault(); setFocus(null) }
      return
    }
    if (e.key === "Tab") {
      const target = stockFor(highlighted)
      if (target) {
        e.preventDefault()
        setFocus(target)
        setQuery("")
      }
    }
  }

  const data = search.data
  const companies = data?.companies ?? []
  // Results arrive after the text actions render, so cmdk would keep "문서 검색" highlighted. Point Enter/Tab at the best row instead.
  useEffect(() => {
    if (focus) return
    if (!q) { setHighlighted(recent.length ? `recent-${recent[0].market}-${recent[0].code}` : ""); return }
    if (intent === "sentence") { setHighlighted(discoverFirst(q) ? "sentence-discover" : "sentence-chat"); return }
    if (data?.query !== q) return
    setHighlighted(data.companies[0] ? `kr-${data.companies[0].stock_code}` : data.us[0] ? `us-${data.us[0].ticker}` : data.groups[0] ? `group-${data.groups[0].id}` : "text-docs")
  }, [q, data, intent, focus, recent])
  /** cmdk의 현재 선택값(value)에서 종목을 찾는다: kr-코드 · us-티커 · recent-시장-코드 · today-코드-라벨. */
  function stockFor(value: string): Focus | null {
    if (value.startsWith("kr-")) { const c = companies.find(item => item.stock_code === value.slice(3)); return c ? { code: c.stock_code, name: c.name, market: "kr" } : null }
    if (value.startsWith("us-")) { const u = data?.us.find(item => item.ticker === value.slice(3)); return u ? { code: u.ticker, name: u.name, market: "us" } : null }
    if (value.startsWith("recent-")) { const [, market, code] = value.split("-"); const r = recent.find(item => item.code === code && item.market === market); return r ? { code: r.code, name: r.name, market: r.market } : null }
    if (value.startsWith("today-")) { const t = today.data?.items.find(item => value === `today-${item.stock_code}-${item.label}`); return t ? { code: t.stock_code, name: t.name, market: "kr" } : null }
    return null
  }
  const visibleCompanies = showAll ? companies : companies.slice(0, 5)
  const pages = q ? PAGES.filter(p => `${p.label} ${p.hint} ${p.keywords}`.toLowerCase().includes(q.toLowerCase())).slice(0, 5) : PAGES.filter(p => p.pinned)
  const hasResults = !!data && (companies.length || data.us.length || data.entities.length || data.groups.length || data.projects.length)

  return (
    <CommandDialog open={open} onOpenChange={setOpen} title="옴니바" description="종목·화면 이동, 문서 검색, 질문" className="sm:max-w-2xl">
      <Command shouldFilter={false} onKeyDown={onKeyDown} loop value={highlighted} onValueChange={setHighlighted}>
        <div className="relative">
          <CommandInput placeholder={focus ? `${focus.name}에 대해 할 일…` : "종목·티커·인물·화면, 또는 문장으로 질문… (⌘K)"} value={query} onValueChange={value => { setQuery(value); setShowAll(false) }} />
          {(intent !== "empty" || focus) && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">{focus ? `${focus.name} · 행동` : INTENT_LABEL[intent]}</span>}
        </div>
        <CommandList className="max-h-[60vh]">
          {focus ? <StockActions focus={focus} groups={groups.data?.items ?? []} adding={addMember.isPending} onOpen={path => openCompany(focus, path)} onBack={() => setFocus(null)}
            onAddToGroup={async groupId => { try { const detail = await addMember.mutateAsync({ groupId, stock_code: focus.code }); toast.success(`${focus.name}을(를) ‘${detail.name}’에 추가했습니다.`); setOpen(false) } catch (error) { toast.error(error instanceof Error ? error.message : "묶음에 추가하지 못했습니다.") } }} /> : <>
          {!q && <>
            {recent.length > 0 && <CommandGroup heading="최근 본 종목">
              <div className="flex flex-wrap gap-1.5 px-2 pb-2">{recent.map(item => <CommandItem key={`${item.market}:${item.code}`} value={`recent-${item.market}-${item.code}`} data-stock={item.code} data-name={item.name} data-market={item.market} className="h-7 rounded-full border px-3 py-0 text-xs data-[selected=true]:border-primary" onSelect={() => openCompany(item)}>{item.name}</CommandItem>)}</div>
            </CommandGroup>}
            {!!today.data?.items.length && <CommandGroup heading={`오늘 켜진 감시 신호 · ${today.data.as_of ?? ""}`}>
              {today.data.items.slice(0, 5).map(signal => <CommandItem key={`${signal.group_id}-${signal.stock_code}-${signal.label}`} value={`today-${signal.stock_code}-${signal.label}`} data-stock={signal.stock_code} data-name={signal.name} data-market="kr" onSelect={() => openCompany({ code: signal.stock_code, name: signal.name, market: "kr" })}>
                <Row icon={<Layers className="size-4" />} title={signal.name} sub={`${signal.label} · ${signal.group_name}`} right={signal.stock_code} />
              </CommandItem>)}
              <CommandItem value="today-all" onSelect={() => go("/follow/stocks")}><Row icon={<Layers className="size-4" />} title="종목 묶음에서 전체 보기" /></CommandItem>
            </CommandGroup>}
            <CommandGroup heading="바로 가기">{pages.map(p => <CommandItem key={p.to} value={`page-${p.to}`} onSelect={() => go(p.to)}><Row icon={<p.icon className="size-4" />} title={p.label} sub={p.hint} /></CommandItem>)}</CommandGroup>
          </>}

          {q && intent === "sentence" && <CommandGroup heading="이 문장으로">
            {(discoverFirst(q) ? ["discover", "chat"] : ["chat", "discover"]).map(kind => kind === "discover"
              ? <CommandItem key="discover" value="sentence-discover" onSelect={() => go(`/discover?q=${encodeURIComponent(q)}`)}><Row icon={<ScanSearch className="size-4" />} title="종목 발견에서 조건으로 검색" sub="AI가 조건을 해석 → 후보·차트" right={<CornerDownLeft className="size-3.5" />} /></CommandItem>
              : <CommandItem key="chat" value="sentence-chat" onSelect={() => go(`/chat?q=${encodeURIComponent(q)}`)}><Row icon={<Sparkles className="size-4 text-hypothesis" />} title="대화에서 질문" sub="수집 문서 근거로 답변" /></CommandItem>)}
            <CommandItem value="sentence-docs" onSelect={() => go(`/feed?q=${encodeURIComponent(q)}`)}><Row icon={<FileSearch className="size-4" />} title="문서 검색" sub="의미 기반 · 전체 수집 자료" /></CommandItem>
          </CommandGroup>}

          {q && companies.length > 0 && <CommandGroup heading={`종목 · 시가총액순${companies.length > 5 ? ` · ${formatNumber(companies.length)}개` : ""}`}>
            {visibleCompanies.map(c => <CommandItem key={c.stock_code} value={`kr-${c.stock_code}`} data-stock={c.stock_code} data-name={c.name} data-market="kr" onSelect={() => openCompany({ code: c.stock_code, name: c.name, market: "kr" })}>
              <Row icon={<Building2 className="size-4" />} title={<Highlight text={c.name} q={q} />}
                sub={[c.market, c.sector, c.in_groups.length ? `${c.in_groups[0]}에 있음` : null].filter(Boolean).join(" · ")}
                right={<span className="flex flex-col items-end leading-tight"><span>{c.close != null ? <>{formatNumber(c.close)} <span className={c.change_pct == null ? "" : c.change_pct > 0 ? "text-up" : c.change_pct < 0 ? "text-down" : ""}>{c.change_pct != null ? formatPercent(c.change_pct) : ""}</span></> : c.stock_code}</span><span>{c.market_cap != null ? formatKrw(c.market_cap) : c.stock_code}</span></span>} />
            </CommandItem>)}
            {companies.length > 5 && !showAll && <CommandItem value="more-companies" onSelect={() => setShowAll(true)}><Row icon={<span className="text-xs">+{companies.length - 5}</span>} title="더 보기" sub="시가총액순 나머지" /></CommandItem>}
          </CommandGroup>}

          {q && !!data?.us.length && <CommandGroup heading="미국 종목">
            {data.us.map(u => <CommandItem key={u.ticker} value={`us-${u.ticker}`} data-stock={u.ticker} data-name={u.name} data-market="us" onSelect={() => openCompany({ code: u.ticker, name: u.name, market: "us" })}>
              <Row icon={<Globe className="size-4" />} title={<Highlight text={u.name} q={q} />} sub={u.group_label ?? "도시에"} right={u.ticker} />
            </CommandItem>)}
          </CommandGroup>}

          {q && !!(data?.groups.length || data?.projects.length) && <CommandGroup heading="묶음·프로젝트">
            {data!.groups.map(g => <CommandItem key={`g-${g.id}`} value={`group-${g.id}`} onSelect={() => go(`/follow/stocks?group=${g.id}`)}><Row icon={<Layers className="size-4" />} title={<Highlight text={g.name} q={q} />} sub={`${g.kind === "portfolio" ? "포트폴리오" : "관심"} 묶음 · ${formatNumber(g.member_count)}종목`} /></CommandItem>)}
            {data!.projects.map(p => <CommandItem key={`p-${p.id}`} value={`project-${p.id}`} onSelect={() => go(`/study/projects/${p.id}`)}><Row icon={<NotebookPen className="size-4" />} title={<Highlight text={p.title} q={q} />} sub="스터디 프로젝트" /></CommandItem>)}
          </CommandGroup>}

          {q && !!data?.entities.length && <CommandGroup heading="인물·테마">
            {data.entities.map(e => <CommandItem key={`e-${e.id}`} value={`entity-${e.id}`} onSelect={() => go(e.type === "person" ? `/person?name=${encodeURIComponent(e.name)}` : `/feed?industry=${encodeURIComponent(e.name)}`)}>
              <Row icon={e.type === "person" ? <User className="size-4" /> : <Tag className="size-4" />} title={<Highlight text={e.name} q={q} />} sub={e.type === "person" ? "인물" : e.type === "theme" ? "테마 · 피드" : "섹터 · 피드"} />
            </CommandItem>)}
          </CommandGroup>}

          {q && intent !== "sentence" && <>
            <CommandSeparator />
            <CommandGroup heading="이 글자로">
              <CommandItem value="text-docs" onSelect={() => go(`/feed?q=${encodeURIComponent(q)}`)}><Row icon={<FileSearch className="size-4" />} title="문서 검색" sub="의미 기반 · 전체 수집 자료" /></CommandItem>
              <CommandItem value="text-discover" onSelect={() => go(`/discover?q=${encodeURIComponent(q)}`)}><Row icon={<ScanSearch className="size-4" />} title="종목 발견에서 조건으로 검색" /></CommandItem>
              <CommandItem value="text-tag" onSelect={() => go(`/feed?industry=${encodeURIComponent(q)}`)}><Row icon={<Tag className="size-4" />} title="태그 피드 보기" /></CommandItem>
            </CommandGroup>
          </>}
          {q && intent === "sentence" && q.length >= 8 && !/\?$/.test(q) && <CommandGroup heading="기록">
            <CommandItem value="remember" onSelect={() => !inject.isPending && inject.mutate(q)}><Row icon={<NotebookPen className="size-4 text-hypothesis" />} title="내 지식으로 저장" sub="가설 · 검색·답변에 반영" /></CommandItem>
          </CommandGroup>}
          {q && pages.length > 0 && <CommandGroup heading="이동">{pages.map(p => <CommandItem key={p.to} value={`page-${p.to}`} onSelect={() => go(p.to)}><Row icon={<p.icon className="size-4" />} title={<Highlight text={p.label} q={q} />} sub={p.hint} /></CommandItem>)}</CommandGroup>}
          {q && search.isFetched && !hasResults && pages.length === 0 && intent !== "sentence" && <CommandEmpty>일치하는 종목·화면이 없습니다. 위의 문서 검색이나 종목 발견을 써보세요.</CommandEmpty>}
          </>}
        </CommandList>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-1.5 text-[11px] text-muted-foreground">
          <span><kbd className="rounded border px-1">↑↓</kbd> 이동 · <kbd className="rounded border px-1">Enter</kbd> 열기 · <kbd className="rounded border px-1">Tab</kbd> 종목 행동{focus && <> · <kbd className="rounded border px-1">←</kbd> 목록으로</>}</span>
          <span>{q ? "정렬: 접두 일치 › 시가총액" : "⌘K · / 로 열기"}</span>
        </div>
      </Command>
    </CommandDialog>
  )
}

function StockActions({ focus, groups, adding, onOpen, onBack, onAddToGroup }: { focus: Focus; groups: { id: number; name: string; kind: string; member_count: number }[]; adding: boolean; onOpen: (path?: string) => void; onBack: () => void; onAddToGroup: (groupId: number) => void }) {
  const base = focus.market === "us" ? `/us/${focus.code}` : `/analyze/${focus.code}`
  return <>
    <CommandGroup heading={`${focus.name} · ${focus.code}`}>
      <CommandItem value="back" onSelect={onBack}><Row icon={<ArrowLeft className="size-4" />} title="목록으로" /></CommandItem>
      <CommandItem value="act-summary" onSelect={() => onOpen(focus.market === "us" ? base : `${base}/summary`)}><Row icon={<Building2 className="size-4" />} title="기업 개요" sub={focus.market === "us" ? "도시에·웹 조사 보고서" : "웹 조사 보고서·차트"} /></CommandItem>
      {focus.market === "kr" && <>
        <CommandItem value="act-financials" onSelect={() => onOpen(`${base}/financials`)}><Row icon={<Table2 className="size-4" />} title="실적·사업" sub="분기 표" /></CommandItem>
        <CommandItem value="act-mentions" onSelect={() => onOpen(`${base}/mentions`)}><Row icon={<BookOpen className="size-4" />} title="자료" sub="뉴스·공시·유튜브" /></CommandItem>
        <CommandItem value="act-research" onSelect={() => onOpen(`${base}/summary?mode=research`)}><Row icon={<ScanSearch className="size-4" />} title="가격·근거 조사 보기" sub="차트와 저장 자료" /></CommandItem>
      </>}
    </CommandGroup>
    {focus.market === "kr" && <CommandGroup heading="묶음에 추가">
      {groups.length === 0 && <CommandItem value="no-groups" onSelect={() => onOpen("/follow/stocks")}><Row icon={<FolderPlus className="size-4" />} title="아직 묶음이 없습니다 — 종목 묶음에서 만들기" /></CommandItem>}
      {groups.map(g => <CommandItem key={g.id} value={`add-${g.id}`} disabled={adding} onSelect={() => onAddToGroup(g.id)}><Row icon={<Layers className="size-4" />} title={g.name} sub={`${g.kind === "portfolio" ? "포트폴리오" : "관심"} · ${formatNumber(g.member_count)}종목`} /></CommandItem>)}
    </CommandGroup>}
  </>
}
