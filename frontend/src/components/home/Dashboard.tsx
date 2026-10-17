import { useEffect, useMemo, useRef, useState } from "react"
import ReactGridLayout, { useContainerWidth, type Compactor, type EventCallback, type LayoutItem } from "react-grid-layout"
import "react-grid-layout/css/styles.css"
import { Plus } from "lucide-react"
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
import { PRESETS, WIDGET_BY_ID } from "@/components/widgets/registry"
import { WidgetGallery } from "@/components/widgets/WidgetGallery"
import {
  aimAt, COLS, fromEntries, MAX_IN_ROW, move, place, resizeWidth, tidy, toEntries,
  type Heights, type Rows, type Spans, type Target,
} from "@/components/widgets/rows"

/* 격자: 행 10px · 간격 12px — 높이를 촘촘하게 맞춘다. 1칸 높이(px) = 22h − 12 */
const ROW_PX = 10
const GAP = 12
const LAYOUT_NAME = "home-v2"     // 줄 배치(높이 단위 10px) — 옛 'home'(72px 행)과 단위가 달라 새 이름
/** 레지스트리 크기(72px 행 기준)를 10px 행으로 */
const fineH = (coarse: number) => Math.max(3, Math.round((84 * coarse) / (ROW_PX + GAP)))
/** 위젯 본문이 받는 높이 — 기존 본문은 72px 행 기준으로 '작으면 숫자만'을 판단한다 */
const coarseH = (fine: number) => Math.max(1, Math.round(((ROW_PX + GAP) * fine) / 84))

interface Board { rows: Rows; spans: Spans; heights: Heights; widgetOf: Record<string, string>; params: Record<string, Record<string, unknown> | undefined> }

/** 프리셋 → 줄: 레지스트리 폭대로 왼쪽부터 채우고 12칸·3개가 넘으면 다음 줄 */
function presetBoard(widgets: string[]): Board {
  const b: Board = { rows: [], spans: {}, heights: {}, widgetOf: {}, params: {} }
  let row: string[] = [], used = 0
  const flush = () => { if (row.length) b.rows.push(row); row = []; used = 0 }
  widgets.forEach((w, n) => {
    const def = WIDGET_BY_ID[w]
    if (!def) return
    if (used + def.size.w > COLS || row.length >= MAX_IN_ROW) flush()
    const id = `${w}#${n}`
    row.push(id); used += def.size.w
    b.widgetOf[id] = w; b.spans[id] = def.size.w; b.heights[id] = fineH(def.size.h)
  })
  flush()
  return b
}

/**
 * 홈 › 대시보드 — 줄 배치 위젯 보드 (docs/specs/home-widgets.md).
 * 손잡이로 끌어 다른 줄에 끼우거나 새 줄로, 아래 가장자리로 높이, 위젯 사이 경계로 이웃과 폭을 주고받는다.
 * 늘 바꿀 수 있고(편집 모드 없음), 놓을 때마다 서버에 저장한다. 빼기·프리셋은 되돌릴 수 있다.
 */
export default function Dashboard() {
  const saved = useDashboardLayout(LAYOUT_NAME)
  const [board, setBoard] = useState<Board | null>(null)
  const [galleryOpen, setGalleryOpen] = useState(false)
  const [presetAsk, setPresetAsk] = useState<string | null>(null)
  const { width, containerRef, mounted } = useContainerWidth()

  useEffect(() => {
    if (board || saved.isPending || saved.isError) return
    if (!saved.data) { setBoard(presetBoard(PRESETS[0].widgets)); return }
    const known = saved.data.filter(e => WIDGET_BY_ID[e.widget])
    const { rows, spans, heights } = fromEntries(known)
    setBoard({ rows, spans, heights, widgetOf: Object.fromEntries(known.map(e => [e.i, e.widget])), params: Object.fromEntries(known.map(e => [e.i, e.params])) })
  }, [saved.data, saved.isPending, saved.isError, board])

  const persist = (b: Board) => saved.save.mutate(
    toEntries(b.rows, b.spans, b.heights, i => b.widgetOf[i], i => fineH(WIDGET_BY_ID[b.widgetOf[i]]?.size.h ?? 3), b.params),
    { onError: () => toast.error("배치를 저장하지 못했습니다. 잠시 뒤 다시 바꿔 보세요.") },
  )
  const commit = (next: Board, undo?: { label: string; prev: Board }) => {
    setBoard(next); persist(next)
    if (undo) toast(undo.label, { action: { label: "되돌리기", onClick: () => { setBoard(undo.prev); persist(undo.prev) } } })
  }

  /* 정렬기는 한 번 만들고 최신 상태는 ref로 읽는다 — 끄는 동안 이웃이 미리 비켜 준다 */
  const boardRef = useRef(board); boardRef.current = board
  const dragRef = useRef<{ id: string; target: Target }>(undefined)
  const liveH = useRef<{ id: string; h: number }>(undefined)
  const liveW = useRef<{ rows: Rows; spans: Spans }>(undefined)
  const resizingRef = useRef<string>(undefined)
  const heightOf = (id: string) => liveH.current?.id === id ? liveH.current.h : boardRef.current?.heights[id] ?? 10
  const compactor: Compactor = useMemo(() => ({
    type: "vertical", allowOverlap: false,
    compact(layout: readonly LayoutItem[]) {
      const b = boardRef.current
      if (!b) return [...layout]
      let rows = tidy(liveW.current?.rows ?? b.rows, layout.map(l => l.i))
      const d = dragRef.current
      if (d) rows = move(rows, d.id, d.target)
      const pos = new Map(place(rows, heightOf, liveW.current?.spans ?? b.spans, resizingRef.current).map(p => [p.i, p]))
      return layout.map(l => ({ ...l, ...pos.get(l.i), static: false, moved: false }))
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [])

  const gridLayout: LayoutItem[] = useMemo(() => {
    if (!board) return []
    return place(board.rows, id => board.heights[id] ?? 10, board.spans).map(p => {
      const def = WIDGET_BY_ID[board.widgetOf[p.i]]
      return { ...p, minW: 2, minH: def?.flat ? 3 : 6 }
    })
  }, [board])

  const aim = (id: string, e: Event): Target | undefined => {
    const grid = containerRef.current?.querySelector(".react-grid-layout")
    const pt = "touches" in e ? (e as TouchEvent).changedTouches[0] : (e as MouseEvent)
    if (!grid || !pt || !boardRef.current) return undefined
    const rect = grid.getBoundingClientRect()
    const colW = (width - GAP * (COLS + 1)) / COLS
    return aimAt(boardRef.current.rows, heightOf, id, (pt.clientX - rect.left - GAP) / (colW + GAP), (pt.clientY - rect.top) / (ROW_PX + GAP))
  }
  const onDrag: EventCallback = (_l, _o, item, _p, e) => { if (item) { const t = aim(item.i, e); if (t) dragRef.current = { id: item.i, target: t } } }
  const onDragStop: EventCallback = (_l, _o, item, _p, e) => {
    const t = item ? aim(item.i, e) ?? dragRef.current?.target : undefined
    dragRef.current = undefined
    const b = boardRef.current
    if (item && t && b) commit({ ...b, rows: move(b.rows, item.i, t) })
  }
  const onResize: EventCallback = (_l, old, item) => {
    const b = boardRef.current
    if (!item || !old || !b) return
    resizingRef.current = item.i
    if (item.h !== old.h) liveH.current = { id: item.i, h: item.h }
    if (item.w !== old.w) liveW.current = resizeWidth(b.rows, item.i, item.w, b.spans)
  }
  const onResizeStop: EventCallback = (l, old, item, p, e, el) => {
    onResize(l, old, item, p, e, el)
    const b = boardRef.current
    const h = liveH.current, w = liveW.current
    liveH.current = undefined; liveW.current = undefined; resizingRef.current = undefined
    if (!b || (!h && !w)) return
    commit({ ...b, ...(w ?? {}), heights: h ? { ...b.heights, [h.id]: h.h } : b.heights })
  }

  const active = useMemo(() => new Set(Object.entries(board?.widgetOf ?? {}).filter(([i]) => board?.rows.some(r => r.includes(i))).map(([, w]) => w)), [board])
  const add = (w: string) => {
    const b = boardRef.current, def = WIDGET_BY_ID[w]
    if (!b || !def) return
    let n = 0
    while (b.widgetOf[`${w}#${n}`]) n++
    const id = `${w}#${n}`
    commit({ ...b, rows: [[id], ...b.rows], widgetOf: { ...b.widgetOf, [id]: w }, spans: { ...b.spans, [id]: COLS }, heights: { ...b.heights, [id]: fineH(def.size.h) } })
    toast.success(`'${def.title}'을 맨 위에 넣었어요. 손잡이로 끌어 옮기세요.`)
  }
  const removeIds = (ids: string[], label: string) => {
    const b = boardRef.current
    if (!b) return
    commit({ ...b, rows: b.rows.map(r => r.filter(i => !ids.includes(i))).filter(r => r.length) }, { label, prev: b })
  }
  const applyPreset = (key: string) => {
    const p = PRESETS.find(x => x.key === key), b = boardRef.current
    if (!p || !b) return
    commit(presetBoard(p.widgets), { label: `'${p.label}' 프리셋으로 바꿨어요.`, prev: b })
    setPresetAsk(null)
  }

  if (saved.isError) return <ErrorState message="대시보드 배치를 불러오지 못했습니다." onRetry={() => void saved.refetch()} />

  const ids = board?.rows.flat() ?? []
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">프리셋</span>
        <ToggleGroup type="single" size="sm" variant="outline" value="" onValueChange={v => v && setPresetAsk(v)} aria-label="프리셋 적용">
          {PRESETS.map(p => <ToggleGroupItem key={p.key} value={p.key} className="px-3 text-xs">{p.label}</ToggleGroupItem>)}
        </ToggleGroup>
        <span className="ml-auto text-xs text-muted-foreground">손잡이로 옮기고, 아래·옆 가장자리로 크기를 바꿔요</span>
        <Button size="sm" onClick={() => setGalleryOpen(true)}><Plus className="size-3.5" />위젯 추가</Button>
      </div>

      <div ref={containerRef} className="-mx-3">
        {!board || !mounted ? (
          <div className="grid grid-cols-12 gap-3 px-3">{[12, 12, 6, 6, 3, 3, 3, 3].map((w, n) => <Skeleton key={n} className="h-36 rounded-[var(--radius-card)]" style={{ gridColumn: `span ${w}` }} />)}</div>
        ) : !ids.length ? (
          <div className="mx-3 rounded-[var(--radius-card)] border border-dashed p-8 text-center text-sm text-muted-foreground">
            위젯이 없어요. <Button variant="link" className="h-auto p-0" onClick={() => setGalleryOpen(true)}>위젯 추가</Button>로 홈을 채우거나 프리셋을 고르세요.
          </div>
        ) : (
          <ReactGridLayout
            width={width}
            layout={gridLayout}
            gridConfig={{ cols: COLS, rowHeight: ROW_PX, margin: [GAP, GAP] }}
            dragConfig={{ enabled: true, handle: ".widget-handle" }}
            resizeConfig={{ enabled: true, handles: ["s", "e"] }}
            compactor={compactor}
            onDragStart={() => { dragRef.current = undefined }}
            onDrag={onDrag}
            onDragStop={onDragStop}
            onResizeStart={onResize}
            onResize={onResize}
            onResizeStop={onResizeStop}
          >
            {ids.map(i => {
              const def = WIDGET_BY_ID[board.widgetOf[i]]
              if (!def) return null
              const p = gridLayout.find(x => x.i === i)
              const h = p?.h ?? board.heights[i] ?? 10
              return <div key={i}>
                <WidgetItem defId={def.id} w={p?.w ?? def.size.w} fine={h} params={board.params[i]}
                  onRemove={() => removeIds([i], `'${def.title}'을 뺐어요.`)} />
              </div>
            })}
          </ReactGridLayout>
        )}
      </div>

      <WidgetGallery open={galleryOpen} onOpenChange={setGalleryOpen} active={active} onAdd={add}
        onRemove={w => removeIds(ids.filter(i => board?.widgetOf[i] === w), `'${WIDGET_BY_ID[w]?.title}'을 뺐어요.`)} />

      <AlertDialog open={!!presetAsk} onOpenChange={v => !v && setPresetAsk(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>'{PRESETS.find(p => p.key === presetAsk)?.label}' 프리셋으로 바꿀까요?</AlertDialogTitle>
            <AlertDialogDescription>지금 배치를 이 프리셋 구성으로 바꿉니다. 바꾼 뒤에도 '되돌리기'로 돌아올 수 있어요.</AlertDialogDescription>
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

function WidgetItem({ defId, w, fine, params, onRemove }: { defId: string; w: number; fine: number; params?: Record<string, unknown>; onRemove: () => void }) {
  const def = WIDGET_BY_ID[defId]
  const meta = def.useMeta()
  const h = coarseH(fine)
  return (
    <WidgetFrame title={def.title} asOf={meta.asOf} stale={meta.stale} detailPath={def.detailPath} onRemove={onRemove} flat={def.flat && h <= 1}>
      <def.Body w={w} h={h} params={params} />
    </WidgetFrame>
  )
}
