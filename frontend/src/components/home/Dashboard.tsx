import { useEffect, useMemo, useState } from "react"
import ReactGridLayout, { useContainerWidth, verticalCompactor, type Layout } from "react-grid-layout"
import "react-grid-layout/css/styles.css"
import { Check, Pencil, Plus } from "lucide-react"
import { toast } from "sonner"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ErrorState } from "@/components/shared/ErrorState"
import { WidgetFrame } from "@/components/shared/WidgetFrame"
import { useDashboardLayout } from "@/hooks/useDashboard"
import { append, COLS, normalize, pack, type LayoutEntry } from "@/components/widgets/layout"
import { PRESETS, WIDGET_BY_ID, WIDGET_SIZES } from "@/components/widgets/registry"
import { WidgetGallery } from "@/components/widgets/WidgetGallery"
import type { WidgetDef } from "@/components/widgets/types"

const ROW_HEIGHT = 72
const GAP = 12
const defaultLayout = () => pack(PRESETS[0].widgets, WIDGET_SIZES)

/**
 * 홈 › 대시보드 — 위젯 격자 (docs/specs/home-widgets.md).
 * 평소엔 고정, '편집'에서만 끌기·크기 조절·삭제. 편집을 끝낼 때 한 번 서버에 저장한다.
 */
export default function Dashboard() {
  const saved = useDashboardLayout("home")
  const [layout, setLayout] = useState<LayoutEntry[] | null>(null)
  const [editing, setEditing] = useState(false)
  const [galleryOpen, setGalleryOpen] = useState(false)
  const [presetAsk, setPresetAsk] = useState<string | null>(null)
  const { width, containerRef, mounted } = useContainerWidth()

  // 저장본(없으면 기본 프리셋)으로 한 번 초기화 — 편집 중 다시 덮어쓰지 않는다
  useEffect(() => {
    if (layout || saved.isPending || saved.isError) return
    setLayout(normalize(saved.data ?? defaultLayout(), WIDGET_SIZES))
  }, [saved.data, saved.isPending, saved.isError, layout])

  const persist = (next: LayoutEntry[], done?: () => void) => saved.save.mutate(next, {
    onSuccess: () => done?.(),
    onError: () => toast.error("배치를 저장하지 못했습니다. 편집을 끝내기 전에 다시 시도해 주세요."),
  })

  const active = useMemo(() => new Set((layout ?? []).map(e => e.widget)), [layout])
  const gridLayout: Layout = useMemo(() => (layout ?? []).map(e => {
    const s = WIDGET_SIZES[e.widget]
    return { i: e.i, x: e.x, y: e.y, w: e.w, h: e.h, minW: s.minW, minH: s.minH, maxW: COLS }
  }), [layout])

  const onLayoutChange = (next: Layout) => {
    if (!layout) return
    const pos = new Map(next.map(n => [n.i, n]))
    setLayout(layout.map(e => { const n = pos.get(e.i); return n ? { ...e, x: n.x, y: n.y, w: n.w, h: n.h } : e }))
  }
  const change = (next: LayoutEntry[]) => { setLayout(next); if (!editing) persist(next) }
  const add = (id: string) => change(append(layout ?? [], id, WIDGET_SIZES))
  const removeWidget = (id: string) => change((layout ?? []).filter(e => e.widget !== id))
  const removeInstance = (i: string) => setLayout((layout ?? []).filter(e => e.i !== i))
  const finishEdit = () => {
    const next = normalize(layout ?? [], WIDGET_SIZES)
    setLayout(next)
    persist(next, () => { setEditing(false); toast.success("배치를 저장했습니다.") })
  }
  const applyPreset = (key: string) => {
    const p = PRESETS.find(x => x.key === key)
    if (!p) return
    const next = pack(p.widgets, WIDGET_SIZES)
    setLayout(next); persist(next); setPresetAsk(null)
  }

  if (saved.isError) return <ErrorState message="대시보드 배치를 불러오지 못했습니다." onRetry={() => void saved.refetch()} />

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">프리셋</span>
        <ToggleGroup type="single" size="sm" variant="outline" value="" onValueChange={v => v && setPresetAsk(v)} aria-label="프리셋 적용">
          {PRESETS.map(p => <ToggleGroupItem key={p.key} value={p.key} className="px-3 text-xs">{p.label}</ToggleGroupItem>)}
        </ToggleGroup>
        <div className="ml-auto flex gap-2">
          {editing
            ? <Button size="sm" onClick={finishEdit} disabled={saved.save.isPending}><Check className="size-3.5" />편집 끝내기</Button>
            : <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil className="size-3.5" />편집</Button>}
          <Button size="sm" onClick={() => setGalleryOpen(true)}><Plus className="size-3.5" />위젯 추가</Button>
        </div>
      </div>

      <div ref={containerRef} className="-mx-[6px]">
        {!layout || !mounted ? (
          <div className="grid grid-cols-12 gap-3 px-[6px]">{[12, 12, 6, 6, 4, 4, 4].map((w, n) => <Skeleton key={n} className="h-36 rounded-xl" style={{ gridColumn: `span ${w}` }} />)}</div>
        ) : !layout.length ? (
          <div className="mx-[6px] rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
            위젯이 없어요. <Button variant="link" className="h-auto p-0" onClick={() => setGalleryOpen(true)}>위젯 추가</Button>로 홈을 채우거나 프리셋을 고르세요.
          </div>
        ) : (
          <ReactGridLayout
            width={width}
            layout={gridLayout}
            gridConfig={{ cols: COLS, rowHeight: ROW_HEIGHT, margin: [GAP, GAP], containerPadding: [6, 0] }}
            dragConfig={{ enabled: editing, handle: ".widget-handle" }}
            resizeConfig={{ enabled: editing, handles: ["se"] }}
            compactor={verticalCompactor}
            onLayoutChange={onLayoutChange}
          >
            {layout.map(e => {
              const def = WIDGET_BY_ID[e.widget]
              return <div key={e.i}><WidgetItem def={def} entry={e} editing={editing} onRemove={() => removeInstance(e.i)} /></div>
            })}
          </ReactGridLayout>
        )}
      </div>

      <WidgetGallery open={galleryOpen} onOpenChange={setGalleryOpen} active={active} onAdd={add} onRemove={removeWidget} />

      <AlertDialog open={!!presetAsk} onOpenChange={v => !v && setPresetAsk(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>'{PRESETS.find(p => p.key === presetAsk)?.label}' 프리셋으로 바꿀까요?</AlertDialogTitle>
            <AlertDialogDescription>지금 배치를 이 프리셋의 위젯 구성으로 바꾸고 저장합니다.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>취소</AlertDialogCancel>
            <AlertDialogAction onClick={() => presetAsk && applyPreset(presetAsk)}>바꾸기</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function WidgetItem({ def, entry, editing, onRemove }: { def: WidgetDef; entry: LayoutEntry; editing: boolean; onRemove: () => void }) {
  const meta = def.useMeta()
  const flat = def.flat && entry.h <= 1
  return (
    <WidgetFrame title={def.title} asOf={meta.asOf} stale={meta.stale} detailPath={def.detailPath} editing={editing} onRemove={onRemove} flat={flat}>
      <def.Body w={entry.w} h={entry.h} />
    </WidgetFrame>
  )
}
