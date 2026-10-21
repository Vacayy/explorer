import { useState } from "react"
import { ArrowLeft, Check, LayoutGrid, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { SectionKey } from "@/components/layout/navConfig"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import { GALLERY_SECTIONS, WIDGETS } from "./registry"
import type { WidgetDef } from "./types"

/**
 * 위젯 추가 — 검색 + L1 탭 + 묶음별 목록, 항목마다 추가/추가됨 (docs/specs/home-widgets.md §1).
 * 검색어가 있으면 탭과 무관하게 전체에서 찾는다. 추가됨을 누르면 뺀다.
 * 여러 개 놓는 위젯(multi)은 늘 '추가'이고, 설정을 고르는 위젯(pick='stock')은 종목 검색 단계를 거친다(docs/specs/stock-tracker.md).
 */
export function WidgetGallery({ open, onOpenChange, active, onAdd, onRemove }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  active: Set<string>
  onAdd: (id: string, params?: Record<string, unknown>) => void
  onRemove: (id: string) => void
}) {
  const [tab, setTab] = useState<SectionKey>("home")
  const [q, setQ] = useState("")
  const [picking, setPicking] = useState<WidgetDef | null>(null)
  const pool = q.trim() ? WIDGETS : WIDGETS.filter(w => w.section === tab)
  const groups = [...new Set(pool.map(w => w.group))]
  const close = (v: boolean) => { onOpenChange(v); if (!v) { setQ(""); setPicking(null) } }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-3xl gap-0 p-0 sm:max-w-3xl">
        {picking ? <StockPick def={picking} onBack={() => setPicking(null)} onPick={p => { onAdd(picking.id, p); close(false) }} /> : <>
        <DialogHeader className="px-5 pt-5 pb-3">
          <DialogTitle>위젯 추가</DialogTitle>
          <DialogDescription>홈에 띄울 위젯을 고르세요. 추가된 위젯을 다시 누르면 뺍니다.</DialogDescription>
        </DialogHeader>
        <Command className="rounded-none" loop>
          <div className="px-5"><CommandInput value={q} onValueChange={setQ} placeholder="위젯 · 하위 메뉴 검색" className="h-10" /></div>
          {!q.trim() && (
            <Tabs value={tab} onValueChange={v => setTab(v as SectionKey)} className="px-5 pt-3">
              <TabsList variant="line">
                {GALLERY_SECTIONS.map(s => <TabsTrigger key={s.key} value={s.key}>{s.label}</TabsTrigger>)}
              </TabsList>
            </Tabs>
          )}
          <CommandList className="max-h-[min(520px,60dvh)] px-3 pb-4">
            <CommandEmpty>{q.trim() ? `'${q}'에 맞는 위젯이 없어요.` : "이 메뉴의 위젯은 다음 단계에서 추가됩니다."}</CommandEmpty>
            {groups.map(g => (
              <CommandGroup key={g} heading={g}>
                {pool.filter(w => w.group === g).map(w => {
                  const on = !w.multi && active.has(w.id)
                  return (
                    <CommandItem key={w.id} value={`${w.title} ${w.description} ${w.group}`}
                      onSelect={() => (on ? onRemove(w.id) : w.pick === "stock" ? setPicking(w) : onAdd(w.id))}
                      className="gap-3 py-2">
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground"><LayoutGrid className="size-4" /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium">{w.title}</span>
                        <span className="block truncate text-xs text-muted-foreground">{w.description}</span>
                      </span>
                      {on
                        ? <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground"><Check className="size-3.5" />추가됨</span>
                        : <Button asChild variant="outline" size="sm" className="pointer-events-none shrink-0"><span><Plus className="size-3.5" />추가</span></Button>}
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </>}
      </DialogContent>
    </Dialog>
  )
}


/** 종목 고르기 단계 — 회사 검색(서버) → params {code, name} */
function StockPick({ def, onBack, onPick }: { def: WidgetDef; onBack: () => void; onPick: (p: Record<string, unknown>) => void }) {
  const [q, setQ] = useState("")
  const search = useCompanySearch(q.trim())
  return <>
    <DialogHeader className="px-5 pt-5 pb-3">
      <DialogTitle className="flex items-center gap-2">
        <Button variant="ghost" size="icon-xs" onClick={onBack} aria-label="위젯 목록으로"><ArrowLeft className="size-4" /></Button>{def.title} — 종목 고르기
      </DialogTitle>
      <DialogDescription>{def.description}</DialogDescription>
    </DialogHeader>
    <Command className="rounded-none" shouldFilter={false} loop>
      <div className="px-5"><CommandInput value={q} onValueChange={setQ} placeholder="종목명 또는 코드" className="h-10" autoFocus /></div>
      <CommandList className="max-h-[min(420px,55dvh)] px-3 pb-4">
        <CommandEmpty>{!q.trim() ? "종목명이나 코드를 입력하세요." : search.isLoading ? "찾는 중…" : `'${q}'에 맞는 종목이 없어요.`}</CommandEmpty>
        {!!search.data?.length && <CommandGroup heading="종목">
          {search.data.filter(c => c.stock_code).slice(0, 20).map(c => <CommandItem key={c.stock_code!} value={c.stock_code!} onSelect={() => onPick({ code: c.stock_code, name: c.corp_name })} className="gap-3 py-2">
            <span className="min-w-0 flex-1 text-sm">{c.corp_name}</span><span className="text-xs tabular-nums text-muted-foreground">{c.stock_code}</span>
          </CommandItem>)}
        </CommandGroup>}
      </CommandList>
    </Command>
  </>
}
