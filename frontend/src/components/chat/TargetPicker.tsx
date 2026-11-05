import { forwardRef, useEffect, useImperativeHandle, useState, type ReactNode } from "react"
import { Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Input } from "@/components/ui/input"
import { Kbd } from "@/components/ui/kbd"
import { SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { targetValue, useChatTargets } from "@/hooks/useChatTargets"
import { KIND_NAME, MAX_TARGETS, sameTarget, TARGET_KINDS } from "@/lib/chatTargets"
import { cn } from "@/lib/utils"
import { formatKstSlashDate, formatPercent } from "@/utils/format"
import type { ChatTarget, ChatTargetKind } from "@/types"
import { KIND_ICON } from "./TargetChip"
import { PopoverContent } from "@/components/ui/popover"

/** ⌘K 옴니바를 연다 — 결과 없음에서 '⌘K로 문서 검색 ›' */
function openOmnibar() {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }))
}

/** 종류 칩 (전체·종목·미국·서사·질문·자료·인물·테마·Peer·리포트) — 가로로 넘치면 밀어서 본다 */
export function KindChips({ value, onChange, className }: { value: ChatTargetKind | null; onChange: (k: ChatTargetKind | null) => void; className?: string }) {
  return (
    <div className={cn("overflow-x-auto [scrollbar-width:none]", className)}>
      <ToggleGroup type="single" value={value ?? "all"} onValueChange={v => { if (v) onChange(v === "all" ? null : v as ChatTargetKind) }}
        aria-label="대상 종류" className="w-max gap-1">
        {TARGET_KINDS.map(k => (
          <ToggleGroupItem key={k.label} value={k.kind ?? "all"} size="sm"
            className="h-7 rounded-full bg-muted px-2.5 text-xs font-normal text-muted-foreground aria-pressed:bg-primary aria-pressed:text-primary-foreground max-md:h-9 max-md:px-3.5 max-md:text-[13px]">
            {k.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  )
}

/** 후보 한 줄 — 아이콘 · 이름/둘째 줄 · 오른쪽(종목 등락 · 날짜 · 질문 번호) */
function TargetRow({ t, trailing }: { t: ChatTarget; trailing?: ReactNode }) {
  const Icon = KIND_ICON[t.kind]
  const right = t.kind === "stock" || t.kind === "peer_group"
    ? (t.change_pct != null ? <span className={cn(t.change_pct > 0 ? "text-up" : t.change_pct < 0 ? "text-down" : "")}>{formatPercent(t.change_pct)}</span> : null)
    : t.kind === "question" ? (t.code ?? `#${t.ref}`)
      : t.date ? formatKstSlashDate(t.date, false) : null
  return (
    <div className="flex w-full min-w-0 items-center gap-3">
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-[13px] text-foreground">{t.label}</span>
        {t.sub && <span className="truncate text-[11px] text-muted-foreground">{t.sub}</span>}
      </span>
      {right && <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{right}</span>}
      {trailing}
    </div>
  )
}

/** 불러오는 중 · 오류 · 결과 없음 (팝오버·시트 공통) */
function ListState({ loading, error, empty, query, onRetry }: { loading: boolean; error: boolean; empty: boolean; query: string; onRetry: () => void }) {
  if (loading) return <div data-picker-state="loading" className="space-y-2 p-3"><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-4/5" /><Skeleton className="h-9 w-3/4" /></div>
  if (error) return (
    <div data-picker-state="error" className="flex items-center gap-1 px-3 py-4 text-[13px] text-muted-foreground">
      후보를 못 불러왔어요 ·<Button variant="link" size="sm" className="h-auto p-0 text-[13px]" onClick={onRetry}>다시 시도</Button>
    </div>
  )
  if (empty) return (
    <div data-picker-state="empty" className="space-y-1 px-3 py-4 text-[13px]">
      <p>{query ? `‘${query}’과 맞는 대상이 없어요` : "붙일 대상이 없어요"}</p>
      <Button variant="link" size="sm" className="h-auto p-0 text-xs text-muted-foreground" onClick={openOmnibar}>⌘K로 문서 검색 ›</Button>
    </div>
  )
  return null
}

/** 입력 칸이 팝오버를 움직이는 손잡이 — `@`로 열면 포커스가 입력 칸에 남는다 */
export interface PickerHandle {
  move: (step: 1 | -1) => void
  /** 고른 줄을 붙였으면 true */
  enter: () => boolean
}

/**
 * 데스크톱 팝오버 (Composer의 Popover 안) — 후보 검색과 고른 줄을 여기서 가진다.
 * Composer에 대상 붙이기가 켜졌을 때만 마운트된다(그래서 Composer 자체는 서버 조회 없이도 쓸 수 있다).
 */
export const TargetPopover = forwardRef<PickerHandle, {
  open: boolean
  mode: "at" | "plus"
  query: string
  onQuery: (q: string) => void
  kind: ChatTargetKind | null
  onKind: (k: ChatTargetKind | null) => void
  onPick: (t: ChatTarget) => void
  attached: ChatTarget[]
  full: boolean
  /** 클릭이 이 안이면 닫지 않는다(입력 카드) */
  keepOpenWithin: React.RefObject<HTMLElement | null>
}>(function TargetPopover({ open, mode, query, onQuery, kind, onKind, onPick, attached, full, keepOpenWithin }, ref) {
  const search = useChatTargets(query, kind, open)
  const [highlight, setHighlight] = useState("")
  const free = search.items.filter(t => !attached.some(a => sameTarget(a, t)))
  // 결과가 바뀌면 첫 줄을 고른다(이미 붙은 것은 건너뜀)
  useEffect(() => {
    const first = search.items.find(t => !attached.some(a => sameTarget(a, t)))
    setHighlight(first ? targetValue(first) : "")
  }, [search.items]) // eslint-disable-line react-hooks/exhaustive-deps -- 붙일 때마다 첫 줄로 돌아가지 않게 결과만 본다
  useImperativeHandle(ref, () => ({
    move: step => {
      const values = free.map(targetValue)
      if (!values.length) return
      const i = values.indexOf(highlight)
      setHighlight(values[(i + step + values.length) % values.length] ?? values[0])
    },
    enter: () => {
      const t = free.find(x => targetValue(x) === highlight)
      if (!t || full) return false
      onPick(t)
      return true
    },
  }), [free, highlight, full, onPick])
  return (
    <PopoverContent align="start" sideOffset={6} data-target-picker
      className="w-[min(440px,calc(100vw-2rem))] gap-0 overflow-hidden p-0"
      onOpenAutoFocus={e => { if (mode === "at") e.preventDefault() }}
      onCloseAutoFocus={e => e.preventDefault()}
      onInteractOutside={e => { if (keepOpenWithin.current?.contains(e.target as Node)) e.preventDefault() }}>
      <TargetPickerPanel search={search} query={query} onQuery={mode === "plus" ? onQuery : undefined}
        kind={kind} onKind={onKind} highlight={highlight} onHighlight={setHighlight} onPick={onPick} attached={attached} full={full} />
    </PopoverContent>
  )
})

/**
 * 데스크톱 팝오버 안 목록 (시안 Chat-Tag A) — `@` 뒤 글자(또는 '＋'로 열면 맨 위 검색 칸)로 거르고, 종류별로 묶는다.
 * `@`로 열면 포커스는 입력 칸에 남고 ↑↓·Enter·Esc는 입력 칸이 받아 `highlight`를 움직인다(Composer).
 */
function TargetPickerPanel({ search, query, onQuery, kind, onKind, highlight, onHighlight, onPick, attached, full }: {
  search: ReturnType<typeof useChatTargets>
  query: string
  /** '＋'로 열었을 때만 — 팝오버 맨 위 검색 칸 */
  onQuery?: (q: string) => void
  kind: ChatTargetKind | null
  onKind: (k: ChatTargetKind | null) => void
  highlight: string
  onHighlight: (v: string) => void
  onPick: (t: ChatTarget) => void
  attached: ChatTarget[]
  full: boolean
}) {
  const loading = search.isLoading || (search.isFetching && search.isPlaceholderData && !search.items.length)
  return (
    <Command shouldFilter={false} value={highlight} onValueChange={onHighlight} loop className="rounded-none bg-transparent">
      {onQuery && <CommandInput autoFocus value={query} onValueChange={onQuery} placeholder="종목·서사·질문·자료 찾기" />}
      <KindChips value={kind} onChange={onKind} className="border-b px-2 py-2" />
      {/* 팝오버가 화면 밖으로 나가지 않게 — Radix가 알려 주는 남은 높이에서 칩 줄·검색 칸·바닥 줄을 뺀다 */}
      <CommandList className={onQuery ? "max-h-[min(380px,calc(var(--radix-popover-content-available-height)-140px))]" : "max-h-[min(380px,calc(var(--radix-popover-content-available-height)-96px))]"}>
        <ListState loading={loading} error={search.isError && !search.items.length} empty={!loading && !search.isError && !search.items.length}
          query={query.trim()} onRetry={() => search.refetch()} />
        {search.groups.map(g => (
          <CommandGroup key={g.kind} heading={KIND_NAME[g.kind]}>
            {g.items.map(t => {
              const on = attached.some(a => sameTarget(a, t))
              return (
                <CommandItem key={targetValue(t)} value={targetValue(t)} disabled={on || full} onSelect={() => onPick(t)} className="py-2">
                  <TargetRow t={t} trailing={on ? <Check className="size-3.5 text-muted-foreground" aria-label="붙어 있음" /> : undefined} />
                </CommandItem>
              )
            })}
          </CommandGroup>
        ))}
      </CommandList>
      <div className="flex items-center gap-3 border-t px-3 py-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><Kbd>↑↓</Kbd>이동</span>
        <span className="flex items-center gap-1"><Kbd>Enter</Kbd>붙이기</span>
        <span className="flex items-center gap-1"><Kbd>Esc</Kbd>닫기</span>
        <span className={cn("ml-auto", full && "text-foreground")}>{MAX_TARGETS}개까지</span>
      </div>
    </Command>
  )
}

/**
 * 폰 시트 (시안 Mobile-Chat-Tag) — 검색 칸 · 종류 칩 · 목록(여러 개 체크) · 'n개 붙이기'.
 * SheetContent만 그린다 — 열고 닫기는 Composer의 Sheet가 맡는다.
 */
export function TargetSheetContent({ initialQuery, attached, onConfirm }: {
  initialQuery: string
  attached: ChatTarget[]
  onConfirm: (picked: ChatTarget[]) => void
}) {
  const [query, setQuery] = useState(initialQuery)
  const [kind, setKind] = useState<ChatTargetKind | null>(null)
  const [picked, setPicked] = useState<ChatTarget[]>([])
  useEffect(() => { setQuery(initialQuery) }, [initialQuery])
  const search = useChatTargets(query, kind, true)
  const used = attached.filter(a => a.available !== false).length
  const room = MAX_TARGETS - used
  const toggle = (t: ChatTarget) => setPicked(p => p.some(x => sameTarget(x, t)) ? p.filter(x => !sameTarget(x, t)) : p.length >= room ? p : [...p, t])
  const loading = search.isLoading
  return (
    <SheetContent side="bottom" className="max-h-[85dvh] gap-0 rounded-t-2xl p-0 pb-[env(safe-area-inset-bottom)]" showCloseButton={false}>
      <SheetHeader className="flex-row items-center justify-between px-4 pt-4 pb-2">
        <SheetTitle className="text-[15px]">붙일 대상</SheetTitle>
        <SheetDescription className="sr-only">종목·서사·질문·자료를 골라 질문에 붙입니다</SheetDescription>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">{used + picked.length} / {MAX_TARGETS}</span>
      </SheetHeader>
      <div className="space-y-2 px-4 pb-2">
        <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="종목·서사·질문·자료 찾기" aria-label="대상 찾기" className="h-10 bg-muted" />
        <KindChips value={kind} onChange={setKind} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">
        <ListState loading={loading} error={search.isError && !search.items.length} empty={!loading && !search.isError && !search.items.length}
          query={query.trim()} onRetry={() => search.refetch()} />
        {search.groups.map(g => (
          <section key={g.kind}>
            <h3 className="px-3 pt-3 pb-1 text-xs text-muted-foreground">{KIND_NAME[g.kind]}</h3>
            {g.items.map(t => {
              const on = attached.some(a => sameTarget(a, t))
              const checked = on || picked.some(x => sameTarget(x, t))
              const id = `pick-${targetValue(t)}`
              return (
                <label key={id} htmlFor={id} data-sheet-target={targetValue(t)}
                  className={cn("flex min-h-12 items-center gap-2 rounded-lg px-3 py-1.5", checked && "bg-muted", on && "opacity-60")}>
                  <TargetRow t={t} />
                  <Checkbox id={id} checked={checked} disabled={on || (!checked && picked.length >= room)} onCheckedChange={() => toggle(t)} aria-label={`${t.label} 고르기`} />
                </label>
              )
            })}
          </section>
        ))}
      </div>
      <SheetFooter className="border-t px-4 py-3">
        <Button className="h-11 w-full" disabled={!picked.length} onClick={() => { onConfirm(picked); setPicked([]) }}>
          {picked.length ? `${picked.length}개 붙이기` : "붙일 대상을 고르세요"}
        </Button>
      </SheetFooter>
    </SheetContent>
  )
}
