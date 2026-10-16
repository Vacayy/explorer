import { useState } from "react"
import { Check, LayoutGrid, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { SectionKey } from "@/components/layout/navConfig"
import { GALLERY_SECTIONS, WIDGETS } from "./registry"

/**
 * 위젯 추가 — 검색 + L1 탭 + 묶음별 목록, 항목마다 추가/추가됨 (docs/specs/home-widgets.md §1).
 * 검색어가 있으면 탭과 무관하게 전체에서 찾는다. 추가됨을 누르면 뺀다.
 */
export function WidgetGallery({ open, onOpenChange, active, onAdd, onRemove }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  active: Set<string>
  onAdd: (id: string) => void
  onRemove: (id: string) => void
}) {
  const [tab, setTab] = useState<SectionKey>("home")
  const [q, setQ] = useState("")
  const pool = q.trim() ? WIDGETS : WIDGETS.filter(w => w.section === tab)
  const groups = [...new Set(pool.map(w => w.group))]

  return (
    <Dialog open={open} onOpenChange={v => { onOpenChange(v); if (!v) setQ("") }}>
      <DialogContent className="max-w-3xl gap-0 p-0 sm:max-w-3xl">
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
                  const on = active.has(w.id)
                  return (
                    <CommandItem key={w.id} value={`${w.title} ${w.description} ${w.group}`} onSelect={() => (on ? onRemove(w.id) : onAdd(w.id))}
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
      </DialogContent>
    </Dialog>
  )
}
