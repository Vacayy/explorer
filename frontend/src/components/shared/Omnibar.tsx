import { useEffect, useMemo, useState, type ReactNode } from "react"
import { track } from "@/lib/usage"
import { useNavigate } from "react-router-dom"
import {
  ArrowLeft, BookOpen, Building2, CornerDownLeft, FileSearch, FolderPlus, Globe, Home, LineChart, MessageCircleQuestion,
  NotebookPen, ScanSearch, Sparkles, Table2, Tag, User, Layers,
} from "lucide-react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { useAddMember, useGroups } from "@/hooks/useGroups"
import { useProjects } from "@/components/study/useProjects"
import { readRecentStocks, rememberRecentStock } from "@/lib/recentStocks"
import { attachToAi } from "@/lib/aiPanel"
import { formatKrw, formatKstSlashDate, formatNumber, formatPercent } from "@/utils/format"
import { Badge } from "@/components/ui/badge"
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator,
} from "@/components/ui/command"

/**
 * 옴니바 (⌘K · /) — 종목·티커·인물·화면·문장을 한 입력으로 잇는다. D-189.
 * 검색과 순위는 서버(`/api/spine/search`)가 정하고 여기서는 cmdk의 자체 필터를 끈다(shouldFilter=false).
 * 빈 상태는 "돌아갈 곳"(최근 본 종목·오늘 켜진 신호·바로 가기 칩), 종목 행에서 Tab은 그 종목에 대한 행동을 펼친다.
 * 배치는 시안 Search(ia-redesign §4.14): 미국 종목 그룹은 국내 이름이 검색어로 시작하지 않으면 맨 위(미국 기업 탭 대신 주 진입로).
 */

interface SearchCompany { stock_code: string; name: string; market: string | null; sector: string | null; close: number | null; change_pct: number | null; market_cap: number | null; in_groups: string[]; alias?: string | null }
export interface SearchResponse {
  query: string
  companies: SearchCompany[]
  us: { ticker: string; name: string; group_label: string | null }[]
  entities: { id: number; type: string; name: string }[]
  groups: { id: number; name: string; kind: string; member_count: number }[]
  projects: { id: number; title: string }[]
  mentions: { id: number; type: string; name: string; stock_code: string | null }[]
  choseong: boolean
}
export interface TodaySignal { stock_code: string; name: string; label: string; group_id: number; group_name: string; as_of: string; market: "kr" | "us" }

const PAGES = [
  { label: "종목 발견", hint: "자연어 검색·전략·기업 조사", to: "/discover", icon: ScanSearch, keywords: "discover screening 스크리닝 전략 시장 분석 검색", pinned: true },
  { label: "대화", hint: "AI 질문·스레드", to: "/chat", icon: MessageCircleQuestion, keywords: "ask rag chat 대화 질문", pinned: true },
  { label: "스터디", hint: "자료를 모아 함께 공부하기", to: "/study", icon: NotebookPen, keywords: "study 스터디 공부 프로젝트", pinned: true },
  { label: "문서 검색", hint: "전체 수집 자료", to: "/feed?view=documents", icon: FileSearch, keywords: "feed documents 문서 텔레그램 블로그", pinned: true },
  { label: "내 종목", hint: "추적·관심 종목", to: "/home/stocks", icon: Building2, keywords: "follow watchlist 관심목록 팔로우 내 종목 추적", pinned: true },
  { label: "실적 시즌", hint: "컨콜 · 미국 실적 시즌", to: "/follow/transcripts?view=season", icon: LineChart, keywords: "earnings season 실적 시즌 컨콜", pinned: true },
  { label: "종목 묶음", hint: "포트폴리오·관심 종목 감시", to: "/follow/stocks", icon: Layers, keywords: "portfolio watch 묶음 감시 관심 종목 포트폴리오" },
  { label: "Home", hint: "대시보드", to: "/home", icon: Home, keywords: "home stream 홈 대시보드" },
  { label: "Thesis", hint: "내러티브·지식·내 판단", to: "/narrative", icon: Globe, keywords: "thesis narrative worldmodel 월드모델 내러티브 지식" },
  { label: "오늘의 신호", hint: "언급 급증·52주 신고가", to: "/discover#signals", icon: LineChart, keywords: "signal 신호" },
  { label: "기업활동", hint: "홈 › 한국 시장 · 유무증·합병·공개매수", to: "/home/kr#actions", icon: Building2, keywords: "actions 유상증자 기업활동" },
  { label: "소스 관리", hint: "채널·블로그·유튜브", to: "/admin/sources", icon: Globe, keywords: "source 소스 구독 관리 채널 블로그 유튜브" },
  { label: "미국 종목", hint: "컨콜 기업 목록", to: "/follow/transcripts", icon: Globe, keywords: "us 미국 컨콜 transcript" },
  { label: "보관함", hint: "예전 화면", to: "/archive", icon: Home, keywords: "archive 보관함 비교 산업군" },
] as const

type Intent = "empty" | "code" | "ticker" | "choseong" | "name" | "sentence"

/** 입력 형태로 의도를 정한다. 판별이 틀려도 다른 그룹은 그대로 보이므로 값싸게 틀려도 된다. */
function classify(q: string): Intent {
  if (!q) return "empty"
  if (/^\d{6}$/.test(q)) return "code"
  if (/^[A-Z][A-Z0-9.-]{0,5}$/.test(q)) return "ticker"
  if (/^[ㄱ-ㅎ]+$/.test(q)) return "choseong"
  if (/(찾아줘|추려줘|골라줘|보여줘|알려줘|뭐야|왜|어때|\?)$/.test(q) || q.split(/\s+/).length >= 3) return "sentence"
  return "name"
}
/** 문장의 기본 행동: "찾아줘"류·종목 언급은 발견, 질문형은 대화. */
function discoverFirst(q: string): boolean {
  if (/(찾아줘|추려줘|골라줘|스크리닝|종목|조건)/.test(q)) return true
  return !/(\?|알려줘|뭐야|왜|어때|어떻게|비교해줘|설명해줘|정리해줘|분석해줘|요약해줘)$/.test(q)
}
const INTENT_LABEL: Record<Intent, string> = { empty: "", code: "종목 코드", ticker: "미국 티커", choseong: "초성", name: "이름", sentence: "문장" }

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

type Focus = { code: string; name: string; market: "kr" | "us"; board?: string | null; close?: number | null; change_pct?: number | null; in_groups?: string[] }
/** 종목 행동의 두 번째 단계 — 묶음 고르기 · 프로젝트 고르기 */
type Step = "actions" | "groups" | "projects"

export default function Omnibar() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [focus, setFocus] = useState<Focus | null>(null)
  const [step, setStep] = useState<Step>("actions")
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
  const projects = useProjects()
  // 종목의 최근 저장 자료(최대 5건)를 스터디 프로젝트 자료함에 넣는다. projectId 0 = 종목 이름으로 새 프로젝트.
  const toProject = useMutation({
    mutationFn: async ({ projectId, code, name }: { projectId: number; code: string; name: string }) => {
      const evidence = (await api.get<{ items: { doc_id: number | null }[] }>("/api/spine/feed/company-evidence", { params: { company: code, market: "kr", size: 5, page: 1 } })).data
      const ids = [...new Set(evidence.items.map(item => item.doc_id).filter((id): id is number => typeof id === "number"))]
      if (!ids.length) throw new Error("이 종목에 저장된 자료가 없어 프로젝트에 넣을 수 없습니다.")
      let id = projectId, title = projects.data?.find(item => item.id === projectId)?.title ?? ""
      if (!id) { const created = (await api.post<{ id: number }>("/api/spine/study-projects", { title: `${name} 스터디` })).data; id = created.id; title = `${name} 스터디` }
      track('action', 'study.add', { entity: id })
      await api.post(`/api/spine/study-projects/${id}/documents`, { document_ids: ids })
      return { id, title, added: ids.length }
    },
  })
  const recent = useMemo(() => open ? readRecentStocks() : [], [open])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setOpen(v => !v) }
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [])
  useEffect(() => { if (!open) { setQuery(""); setFocus(null); setShowAll(false) } }, [open])
  useEffect(() => { setStep("actions") }, [focus])

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
      if (e.key === "ArrowLeft" || (e.key === "Backspace" && !query)) { e.preventDefault(); if (step !== "actions") setStep("actions"); else setFocus(null) }
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
  // 국내 이름이 검색어로 시작하지 않고 미국 종목이 있으면 미국 그룹을 먼저(시안: '마이크론' → Micron 위, 하나마이크론 아래)
  const usFirst = !!data?.us.length && !companies.some(c => c.name.startsWith(q))
  // Results arrive after the text actions render, so cmdk would keep "문서 검색" highlighted. Point Enter/Tab at the best row instead.
  useEffect(() => {
    if (focus) return
    if (!q) { setHighlighted(recent.length ? `recent-${recent[0].market}-${recent[0].code}` : ""); return }
    if (intent === "sentence") { setHighlighted(discoverFirst(q) ? "sentence-discover" : "sentence-chat"); return }
    if (data?.query !== q) return
    setHighlighted(usFirst ? `us-${data.us[0].ticker}` : data.companies[0] ? `kr-${data.companies[0].stock_code}` : data.us[0] ? `us-${data.us[0].ticker}` : data.groups[0] ? `group-${data.groups[0].id}` : "text-docs")
  }, [q, data, intent, focus, recent, usFirst])
  /** cmdk의 현재 선택값(value)에서 종목을 찾는다: kr-코드 · us-티커 · recent-시장-코드 · today-코드-라벨. */
  function stockFor(value: string): Focus | null {
    if (value.startsWith("kr-")) { const c = companies.find(item => item.stock_code === value.slice(3)); return c ? { code: c.stock_code, name: c.name, market: "kr", board: c.market, close: c.close, change_pct: c.change_pct, in_groups: c.in_groups } : null }
    if (value.startsWith("us-")) { const u = data?.us.find(item => item.ticker === value.slice(3)); return u ? { code: u.ticker, name: u.name, market: "us", board: u.group_label } : null }
    if (value.startsWith("recent-")) { const [, market, code] = value.split("-"); const r = recent.find(item => item.code === code && item.market === market); return r ? { code: r.code, name: r.name, market: r.market } : null }
    if (value.startsWith("mention-")) { const m = data?.mentions.find(item => `mention-${item.id}` === value); return m?.stock_code ? { code: m.stock_code, name: m.name, market: "kr" } : null }
    if (value.startsWith("today-")) { const t = today.data?.items.find(item => value === `today-${item.stock_code}-${item.label}`); return t ? { code: t.stock_code, name: t.name, market: t.market } : null }
    return null
  }
  const visibleCompanies = showAll ? companies : companies.slice(0, 5)
  const pages = q ? PAGES.filter(p => `${p.label} ${p.hint} ${p.keywords}`.toLowerCase().includes(q.toLowerCase())).slice(0, 5) : PAGES.filter(p => 'pinned' in p && p.pinned)
  const hasResults = !!data && (companies.length || data.us.length || data.entities.length || data.groups.length || data.projects.length)

  const usGroup = q && !!data?.us.length && <CommandGroup heading="미국 종목">
            {data.us.map(u => <CommandItem key={u.ticker} value={`us-${u.ticker}`} data-stock={u.ticker} data-name={u.name} data-market="us" onSelect={() => openCompany({ code: u.ticker, name: u.name, market: "us" })}>
              <Row icon={<Globe className="size-4" />} title={<><Highlight text={u.name} q={q} /> <span className="font-mono text-caption font-normal text-muted-foreground">{u.ticker}</span></>} sub={["미국", u.group_label, "도시에·컨콜"].filter(Boolean).join(" · ")} right={<span className="flex items-center gap-2"><MarketBadge market="us" />도시에 ›</span>} />
            </CommandItem>)}
          </CommandGroup>

  return (
    <CommandDialog open={open} onOpenChange={setOpen} title="옴니바" description="종목·화면 이동, 문서 검색, 질문" className="sm:max-w-2xl">
      <Command shouldFilter={false} onKeyDown={onKeyDown} loop value={highlighted} onValueChange={setHighlighted}>
        <div className="relative">
          <CommandInput placeholder={focus ? `${focus.name}에 대해 할 일…` : "종목·티커·인물·화면 이름, 또는 질문 문장"} value={query} onValueChange={value => { setQuery(value); setShowAll(false) }} />
          {(intent !== "empty" || focus) && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">{focus ? `${focus.name} · 행동` : INTENT_LABEL[intent]}</span>}
        </div>
        <CommandList className="max-h-[60vh]">
          {focus ? <StockActions focus={focus} step={step} onStep={setStep} groups={groups.data?.items ?? []} projects={projects.data ?? []} adding={addMember.isPending || toProject.isPending} onOpen={path => openCompany(focus, path)} onBack={() => setFocus(null)}
            onAskAi={() => {
              // AI 대화를 열고 이 종목을 붙여 둔다 — 질문은 보내지 않는다 (ia-redesign §4.14a, D-311)
              track("action", "chat.attach", { entity: focus.code })
              setOpen(false)
              attachToAi({ kind: focus.market === "us" ? "us_stock" : "stock", ref: focus.code, label: focus.name, code: focus.code, change_pct: focus.change_pct ?? null, available: true })
            }}
            onAddToProject={async projectId => { try { const result = await toProject.mutateAsync({ projectId, code: focus.code, name: focus.name }); toast.success(`${focus.name} 자료 ${result.added}건을 ‘${result.title}’에 추가했습니다.`); go(`/study/projects/${result.id}`) } catch (error) { toast.error(error instanceof Error ? error.message : "프로젝트에 추가하지 못했습니다.") } }}
            onAddToGroup={async groupId => { try { const detail = await addMember.mutateAsync({ groupId, stock_code: focus.code }); toast.success(`${focus.name}을(를) ‘${detail.name}’에 추가했습니다.`); setOpen(false) } catch (error) { toast.error(error instanceof Error ? error.message : "묶음에 추가하지 못했습니다.") } }} /> : <>
          {!q && <>
            {recent.length > 0 && <CommandGroup heading="최근 본 종목">
              {recent.map(item => <CommandItem key={`${item.market}:${item.code}`} value={`recent-${item.market}-${item.code}`} data-stock={item.code} data-name={item.name} data-market={item.market} onSelect={() => openCompany(item)}>
                <Row icon={item.market === "us" ? <Globe className="size-4" /> : <Building2 className="size-4" />} title={<>{item.name} <span className="font-mono text-caption font-normal text-muted-foreground">{item.code}</span></>} right={<MarketBadge market={item.market} />} />
              </CommandItem>)}
            </CommandGroup>}
            {!!today.data?.items.length && <CommandGroup heading="오늘 켜진 신호">
              {today.data.items.slice(0, 5).map(signal => <CommandItem key={`${signal.group_id}-${signal.stock_code}-${signal.label}`} value={`today-${signal.stock_code}-${signal.label}`} data-stock={signal.stock_code} data-name={signal.name} data-market={signal.market} onSelect={() => openCompany({ code: signal.stock_code, name: signal.name, market: signal.market })}>
                <Row icon={<Layers className="size-4" />} title={signal.name} sub={`${signal.label} · ${signal.group_name}`} right={<span className="font-mono">{formatKstSlashDate(signal.as_of, false)}</span>} />
              </CommandItem>)}
              <CommandItem value="today-all" onSelect={() => go("/home/stocks")}><Row icon={<Layers className="size-4" />} title={`내 종목에서 전체 보기 · ${formatNumber(today.data.items.length)}건`} /></CommandItem>
            </CommandGroup>}
            <CommandGroup heading="바로 가기">
              <div className="flex flex-wrap gap-1.5 px-2 pb-2">{pages.map(p => <CommandItem key={p.to} value={`page-${p.to}`} className="h-8 rounded-full border px-3 py-0 text-xs data-[selected=true]:border-primary" onSelect={() => go(p.to)}>{p.label}</CommandItem>)}</div>
            </CommandGroup>
          </>}

          {q && intent === "sentence" && <CommandGroup heading="이 문장으로">
            {(discoverFirst(q) ? ["discover", "chat"] : ["chat", "discover"]).map(kind => kind === "discover"
              ? <CommandItem key="discover" value="sentence-discover" onSelect={() => go(`/discover?q=${encodeURIComponent(q)}`)}><Row icon={<ScanSearch className="size-4" />} title="종목 발견에서 조건으로 검색" sub="AI가 조건을 해석 → 후보·차트" right={<CornerDownLeft className="size-3.5" />} /></CommandItem>
              : <CommandItem key="chat" value="sentence-chat" onSelect={() => go(`/chat?q=${encodeURIComponent(q)}`)}><Row icon={<Sparkles className="size-4 text-hypothesis" />} title="대화에서 질문" sub="수집 문서 근거로 답변" /></CommandItem>)}
            <CommandItem value="sentence-docs" onSelect={() => go(`/feed?q=${encodeURIComponent(q)}`)}><Row icon={<FileSearch className="size-4" />} title="문서 검색" sub="의미 기반 · 전체 수집 자료" /></CommandItem>
          </CommandGroup>}
          {q && !!data?.mentions.length && <CommandGroup heading="문장 안에서 알아본 것">
            <div className="flex flex-wrap gap-1.5 px-2 pb-2">{data.mentions.map(m => <CommandItem key={`m-${m.id}`} value={`mention-${m.id}`} data-stock={m.stock_code ?? undefined} data-name={m.name} data-market="kr" className="h-7 rounded-full border px-3 py-0 text-xs data-[selected=true]:border-primary"
              onSelect={() => m.type === "company" && m.stock_code ? openCompany({ code: m.stock_code, name: m.name, market: "kr" }) : go(m.type === "person" ? `/person/${m.id}` : `/feed?industry=${encodeURIComponent(m.name)}`)}>
              {m.type === "company" ? <Building2 className="size-3" /> : m.type === "person" ? <User className="size-3" /> : <Tag className="size-3" />}{m.name}</CommandItem>)}</div>
          </CommandGroup>}

          {usFirst && usGroup}
          {q && companies.length > 0 && <CommandGroup heading={`종목${companies.length > 5 ? ` · 시가총액순 ${formatNumber(companies.length)}개` : ""}`}>
            {visibleCompanies.map(c => <CommandItem key={c.stock_code} value={`kr-${c.stock_code}`} data-stock={c.stock_code} data-name={c.name} data-market="kr" onSelect={() => openCompany({ code: c.stock_code, name: c.name, market: "kr" })}>
              <Row icon={<Building2 className="size-4" />} title={<>{intent === "choseong" ? c.name : <Highlight text={c.name} q={q} />} <span className="font-mono text-caption font-normal text-muted-foreground">{c.stock_code}</span></>}
                sub={[c.alias ? `별칭 “${c.alias}”` : null, c.market, c.sector, c.market_cap != null ? `시총 ${formatKrw(c.market_cap)}` : null].filter(Boolean).join(" · ")}
                right={<span className="flex items-center gap-2">{c.close != null ? <span className="font-mono text-foreground">{formatNumber(c.close)}원 <span className={c.change_pct == null ? "" : c.change_pct > 0 ? "text-up-ink" : c.change_pct < 0 ? "text-down-ink" : ""}>{c.change_pct != null ? formatPercent(c.change_pct) : ""}</span></span> : <span>시세 없음</span>}{c.in_groups.length > 0 && <Badge variant="outline" className="font-normal max-md:hidden">{c.in_groups[0]}</Badge>}</span>} />
            </CommandItem>)}
            {companies.length > 5 && !showAll && <CommandItem value="more-companies" onSelect={() => setShowAll(true)}><Row icon={<span className="text-xs">+{companies.length - 5}</span>} title="더 보기" sub="시가총액순 나머지" /></CommandItem>}
          </CommandGroup>}

          {!usFirst && usGroup}

          {q && !!(data?.groups.length || data?.projects.length) && <CommandGroup heading="묶음·프로젝트">
            {data!.groups.map(g => <CommandItem key={`g-${g.id}`} value={`group-${g.id}`} onSelect={() => go(`/follow/stocks?group=${g.id}`)}><Row icon={<Layers className="size-4" />} title={<Highlight text={g.name} q={q} />} sub={`${g.kind === "portfolio" ? "포트폴리오" : "관심"} 묶음 · ${formatNumber(g.member_count)}종목`} /></CommandItem>)}
            {data!.projects.map(p => <CommandItem key={`p-${p.id}`} value={`project-${p.id}`} onSelect={() => go(`/study/projects/${p.id}`)}><Row icon={<NotebookPen className="size-4" />} title={<Highlight text={p.title} q={q} />} sub="스터디 프로젝트" /></CommandItem>)}
          </CommandGroup>}

          {q && !!data?.entities.length && <CommandGroup heading="인물·테마">
            {data.entities.map(e => <CommandItem key={`e-${e.id}`} value={`entity-${e.id}`} onSelect={() => go(e.type === "person" ? `/person/${e.id}` : `/feed?industry=${encodeURIComponent(e.name)}`)}>
              <Row icon={e.type === "person" ? <User className="size-4" /> : <Tag className="size-4" />} title={<Highlight text={e.name} q={q} />} sub={e.type === "person" ? "인물" : e.type === "theme" ? "테마 · 피드" : "섹터 · 피드"} />
            </CommandItem>)}
          </CommandGroup>}

          {q && intent !== "sentence" && <>
            <CommandSeparator />
            <CommandGroup heading="이 글자로">
              <CommandItem value="text-docs" onSelect={() => go(`/feed?q=${encodeURIComponent(q)}`)}><Row icon={<FileSearch className="size-4" />} title="문서 검색" sub="의미 기반 · 전체 수집 자료" /></CommandItem>
              <CommandItem value="text-discover" onSelect={() => go(`/discover?q=${encodeURIComponent(q)}`)}><Row icon={<ScanSearch className="size-4" />} title="종목 발견에서 조건으로 검색" /></CommandItem>
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

function MarketBadge({ market }: { market: "kr" | "us" }) {
  return <Badge variant="outline" className="font-normal">{market === "us" ? "미국" : "국내"}</Badge>
}

/**
 * 종목 행동 (시안 Search '종목 행동' · Chat-Tag D) — 머리 줄(이름·코드·시장·시세) + 행동.
 * 묶음·프로젝트는 고르는 두 번째 단계로 연다. 'AI에게 묻기'는 AI 대화를 열고 이 종목을 붙여 둔다(D-311).
 */
function StockActions({ focus, step, onStep, groups, projects, adding, onOpen, onBack, onAddToGroup, onAddToProject, onAskAi }: { focus: Focus; step: Step; onStep: (step: Step) => void; groups: { id: number; name: string; kind: string; member_count: number }[]; projects: { id: number; title: string }[]; adding: boolean; onOpen: (path?: string) => void; onBack: () => void; onAddToGroup: (groupId: number) => void; onAddToProject: (projectId: number) => void; onAskAi: () => void }) {
  const base = focus.market === "us" ? `/us/${focus.code}` : `/analyze/${focus.code}`
  const pickable = groups.filter(g => focus.market === "kr" || g.kind === "watch")
  const head = <div className="flex items-center gap-2 border-b px-3 py-2.5 text-sm">
    <span className="font-semibold">{focus.name}</span>
    <span className="font-mono text-caption text-muted-foreground">{focus.code}{focus.board ? ` · ${focus.board}` : ""}</span>
    {focus.close != null && <span className="ml-auto font-mono tabular-nums">{formatNumber(focus.close)}원 <span className={focus.change_pct == null ? "" : focus.change_pct > 0 ? "text-up-ink" : focus.change_pct < 0 ? "text-down-ink" : ""}>{focus.change_pct != null ? formatPercent(focus.change_pct) : ""}</span></span>}
  </div>
  if (step === "groups") return <>
    {head}
    <CommandGroup heading={focus.market === "us" ? "관심 묶음에 추가" : "묶음에 추가"}>
      {pickable.length === 0 && <CommandItem value="no-groups" onSelect={() => onOpen("/follow/stocks")}><Row icon={<FolderPlus className="size-4" />} title="아직 묶음이 없습니다 — 종목 묶음에서 만들기" /></CommandItem>}
      {pickable.map(g => <CommandItem key={g.id} value={`add-${g.id}`} disabled={adding} onSelect={() => onAddToGroup(g.id)}><Row icon={<Layers className="size-4" />} title={g.name} sub={`${g.kind === "portfolio" ? "포트폴리오" : "관심"} · ${formatNumber(g.member_count)}종목`} right={focus.in_groups?.includes(g.name) ? "이미 있음" : undefined} /></CommandItem>)}
      <CommandItem value="step-back" onSelect={() => onStep("actions")}><Row icon={<ArrowLeft className="size-4" />} title="행동으로" /></CommandItem>
    </CommandGroup>
  </>
  if (step === "projects") return <>
    {head}
    <CommandGroup heading="스터디 프로젝트에 자료 추가 · 최근 저장 자료 5건">
      <CommandItem value="project-new" disabled={adding} onSelect={() => onAddToProject(0)}><Row icon={<FolderPlus className="size-4" />} title={`새 프로젝트 “${focus.name} 스터디”`} sub="만들고 자료 넣기" /></CommandItem>
      {projects.slice(0, 6).map(p => <CommandItem key={p.id} value={`project-add-${p.id}`} disabled={adding} onSelect={() => onAddToProject(p.id)}><Row icon={<NotebookPen className="size-4" />} title={p.title} sub="기존 프로젝트" /></CommandItem>)}
      <CommandItem value="step-back" onSelect={() => onStep("actions")}><Row icon={<ArrowLeft className="size-4" />} title="행동으로" /></CommandItem>
    </CommandGroup>
  </>
  const inGroups = focus.in_groups ?? []
  return <>
    {head}
    <CommandGroup heading="행동">
      <CommandItem value="act-summary" onSelect={() => onOpen(focus.market === "us" ? base : `${base}/summary`)}><Row icon={<Building2 className="size-4" />} title="기업 개요" sub={focus.market === "us" ? "도시에·웹 조사 보고서" : "웹 조사 보고서·차트"} /></CommandItem>
      {focus.market === "kr" && <>
        <CommandItem value="act-financials" onSelect={() => onOpen(`${base}/financials`)}><Row icon={<Table2 className="size-4" />} title="실적·사업" sub="분기 표" /></CommandItem>
        <CommandItem value="act-mentions" onSelect={() => onOpen(`${base}/mentions`)}><Row icon={<BookOpen className="size-4" />} title="자료" sub="뉴스·공시·유튜브" /></CommandItem>
        <CommandItem value="act-research" onSelect={() => onOpen(`${base}/summary?mode=research`)}><Row icon={<ScanSearch className="size-4" />} title="가격·근거 조사 보기" sub="차트와 저장 자료" /></CommandItem>
      </>}
      {focus.market === "us" && <>
        <CommandItem value="act-financials" onSelect={() => onOpen(`${base}?tab=financials`)}><Row icon={<Table2 className="size-4" />} title="실적·사업" sub="확보 재무·컨센서스" /></CommandItem>
        <CommandItem value="act-mentions" onSelect={() => onOpen(`${base}?tab=evidence`)}><Row icon={<BookOpen className="size-4" />} title="자료" sub="컨콜·뉴스" /></CommandItem>
      </>}
      <CommandItem value="act-ask-ai" onSelect={onAskAi}><Row icon={<Sparkles className="size-4 text-hypothesis" />} title="AI에게 묻기" sub="이 종목을 붙여 대화 열기" /></CommandItem>
      <CommandItem value="act-groups" onSelect={() => onStep("groups")}><Row icon={<Layers className="size-4" />} title={focus.market === "us" ? "관심 묶음에 추가" : "묶음에 추가"} sub={inGroups.length ? `이미 ${inGroups.join(", ")}에 있음` : "관심·포트폴리오 묶음"} /></CommandItem>
      {focus.market === "kr" && <CommandItem value="act-projects" onSelect={() => onStep("projects")}><Row icon={<NotebookPen className="size-4" />} title="스터디 프로젝트에 자료 추가" sub="최근 저장 자료 5건" /></CommandItem>}
      <CommandItem value="back" onSelect={onBack}><Row icon={<ArrowLeft className="size-4" />} title="목록으로" /></CommandItem>
    </CommandGroup>
  </>
}
