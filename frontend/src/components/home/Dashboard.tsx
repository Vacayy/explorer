import { useMemo, useRef, useState } from "react"
import ReactGridLayout, { useContainerWidth, type Compactor, type EventCallback, type LayoutItem } from "react-grid-layout"
import "react-grid-layout/css/styles.css"
import { ChevronLeft, ChevronRight, Copy, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { WidgetFrame } from "@/components/shared/WidgetFrame"
import { useHomeBoards, type HomeBoard } from "@/hooks/useDashboard"
import { useMediaQuery, MOBILE_QUERY } from "@/hooks/useMediaQuery"
import { WIDGET_BY_ID } from "@/components/widgets/registry"
import { NewBoardDialog } from "@/components/home/NewBoardDialog"
import { WidgetGallery } from "@/components/widgets/WidgetGallery"
import {
  aimAt, COLS, fromEntries, MAX_IN_ROW, move, place, resizeWidth, tidy, toEntries,
  type Entry, type Heights, type Rows, type Spans, type Target,
} from "@/components/widgets/rows"

/* 격자: 행 10px · 간격 12px — 높이를 촘촘하게 맞춘다. 1칸 높이(px) = 22h − 12 */
const ROW_PX = 10
const GAP = 12
/** 레지스트리 크기(72px 행 기준)를 10px 행으로 */
const fineH = (coarse: number) => Math.max(3, Math.round((84 * coarse) / (ROW_PX + GAP)))
/** 위젯 본문이 받는 높이 — 기존 본문은 72px 행 기준으로 '작으면 숫자만'을 판단한다 */
const coarseH = (fine: number) => Math.max(1, Math.round(((ROW_PX + GAP) * fine) / 84))

interface Board { rows: Rows; spans: Spans; heights: Heights; widgetOf: Record<string, string>; params: Record<string, Record<string, unknown> | undefined> }

/** 시스템 프리셋 → 줄: 레지스트리 폭대로 왼쪽부터 채우고 12칸·3개가 넘으면 다음 줄 */
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

/** 저장된 배치 → 보드. 알 수 없는 위젯은 버린다 */
function boardFromEntries(entries: Entry[]): Board {
  const known = entries.filter(e => WIDGET_BY_ID[e.widget])
  const { rows, spans, heights } = fromEntries(known)
  return { rows, spans, heights, widgetOf: Object.fromEntries(known.map(e => [e.i, e.widget])), params: Object.fromEntries(known.map(e => [e.i, e.params])) }
}

const entriesOf = (b: Board) => toEntries(b.rows, b.spans, b.heights, i => b.widgetOf[i], i => fineH(WIDGET_BY_ID[b.widgetOf[i]]?.size.h ?? 3), b.params)
/** 시스템 프리셋의 위젯 목록 → 저장 형식 배치(새 메뉴 만들기) */
export const presetEntries = (widgets: readonly string[]) => entriesOf(presetBoard([...widgets]))

/**
 * 홈 › 메뉴 하나 — 줄 배치 위젯 보드 (docs/specs/home-widgets.md).
 * 손잡이로 끌어 다른 줄에 끼우거나 새 줄로, 아래 가장자리로 높이, 위젯 사이 경계로 이웃과 폭을 주고받는다.
 * 늘 바꿀 수 있고(편집 모드 없음), 놓을 때마다 이 메뉴에 저장한다. 메뉴를 옮겨 다니는 건 화면 이동이라 묻지 않는다.
 * 부모가 메뉴 id로 key를 걸어, 메뉴가 바뀌면 상태를 새로 잡는다.
 */
export default function Dashboard({ menu }: { menu: HomeBoard }) {
  const boards = useHomeBoards()
  const [params, setParams] = useSearchParams()
  const [board, setBoard] = useState<Board>(() => boardFromEntries(menu.items))
  const [galleryOpen, setGalleryOpen] = useState(false)
  const { width, containerRef, mounted } = useContainerWidth()
  // 모바일: 저장된 배치 순서대로 1열, 끌기·크기 조절 없음. 저장된 데스크톱 배치는 건드리지 않는다 (home-widgets.md §모바일)
  const stacked = useMediaQuery(MOBILE_QUERY)

  const persist = (b: Board) => boards.update.mutate({ id: menu.id, items: entriesOf(b) }, { onError: () => toast.error("배치를 저장하지 못했습니다. 잠시 뒤 다시 바꿔 보세요.") })
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

  const active = useMemo(() => new Set(Object.entries(board.widgetOf).filter(([i]) => board.rows.some(r => r.includes(i))).map(([, w]) => w)), [board])
  const add = (w: string, wparams?: Record<string, unknown>) => {
    const b = boardRef.current, def = WIDGET_BY_ID[w]
    if (!b || !def) return
    let n = 0
    while (b.widgetOf[`${w}#${n}`]) n++
    const id = `${w}#${n}`
    commit({ ...b, rows: [[id], ...b.rows], widgetOf: { ...b.widgetOf, [id]: w }, spans: { ...b.spans, [id]: COLS }, heights: { ...b.heights, [id]: fineH(def.size.h) },
      params: wparams ? { ...b.params, [id]: wparams } : b.params })
    toast.success(`'${def.titleOf?.(wparams) ?? def.title}'을 맨 위에 넣었어요. 손잡이로 끌어 옮기세요.`)
  }
  const removeIds = (ids: string[], label: string) => {
    const b = boardRef.current
    if (!b) return
    commit({ ...b, rows: b.rows.map(r => r.filter(i => !ids.includes(i))).filter(r => r.length) }, { label, prev: b })
  }
  const openDetail = (id: string) => setParams(prev => { const next = new URLSearchParams(prev); next.set("widget", id); return next }, { preventScrollReset: true })
  const closeDetail = () => setParams(prev => { const next = new URLSearchParams(prev); next.delete("widget"); return next }, { replace: true, preventScrollReset: true })

  const ids = board.rows.flat()
  const detailDef = WIDGET_BY_ID[params.get("widget") ?? ""]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <BoardMenu menu={menu} />
        <span className="ml-auto text-xs text-muted-foreground max-md:hidden">손잡이로 옮기고, 아래·옆 가장자리로 크기를 바꿔요</span>
        <Button size="sm" className="max-md:ml-auto" onClick={() => setGalleryOpen(true)}><Plus className="size-3.5" />위젯 추가</Button>
      </div>

      <div ref={containerRef} className="-mx-3">
        {!mounted ? (
          <div className="grid grid-cols-12 gap-3 px-3">{[12, 12, 6, 6, 3, 3, 3, 3].map((w, n) => <Skeleton key={n} className="h-36 rounded-[var(--radius-card)]" style={{ gridColumn: `span ${w}` }} />)}</div>
        ) : !ids.length ? (
          <div className="mx-3 rounded-[var(--radius-card)] border border-dashed p-8 text-center text-sm text-muted-foreground">
            이 메뉴에 위젯이 없어요. <Button variant="link" className="h-auto p-0" onClick={() => setGalleryOpen(true)}>위젯 추가</Button>로 채우세요.
          </div>
        ) : stacked ? (
          <div className="flex flex-col gap-3 px-3 [&_.widget-handle]:hidden">
            {ids.map(i => {
              const def = WIDGET_BY_ID[board.widgetOf[i]]
              if (!def) return null
              const h = board.heights[i] ?? 10
              // 본문 밀도는 실제 폭으로 — 데스크톱 1칸 ≈ 100px
              return <div key={i} style={{ height: h * (ROW_PX + GAP) - GAP }}>
                <WidgetItem defId={def.id} w={Math.max(2, Math.round(width / 100))} fine={h} params={board.params[i]}
                  onRemove={() => removeIds([i], `'${def.titleOf?.(board.params[i]) ?? def.title}'을 뺐어요.`)} onOpen={def.Detail && (() => openDetail(def.id))} />
              </div>
            })}
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
                  onRemove={() => removeIds([i], `'${def.titleOf?.(board.params[i]) ?? def.title}'을 뺐어요.`)} onOpen={def.Detail && (() => openDetail(def.id))} />
              </div>
            })}
          </ReactGridLayout>
        )}
      </div>

      {/* 위젯 상세 — URL ?widget=<id>가 단일 소스(뒤로 가기로 닫힌다) */}
      <Dialog open={!!detailDef?.Detail} onOpenChange={v => !v && closeDetail()}>
        <DialogContent showCloseButton={false} className="max-h-[90vh] overflow-y-auto border-0 bg-transparent p-0 shadow-none sm:max-w-2xl">
          <DialogTitle className="sr-only">{detailDef?.title}</DialogTitle>
          <DialogDescription className="sr-only">{detailDef?.description}</DialogDescription>
          {detailDef?.Detail && <detailDef.Detail />}
        </DialogContent>
      </Dialog>

      <WidgetGallery open={galleryOpen} onOpenChange={setGalleryOpen} active={active} onAdd={add}
        onRemove={w => removeIds(ids.filter(i => board.widgetOf[i] === w), `'${WIDGET_BY_ID[w]?.title}'을 뺐어요.`)} />

    </div>
  )
}

/** 이 메뉴의 설정 — 이름 바꾸기·복제·순서·삭제. 삭제만 되돌릴 수 없어 묻는다 */
function BoardMenu({ menu }: { menu: HomeBoard }) {
  const boards = useHomeBoards()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(menu.label)
  const [duplicating, setDuplicating] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const list = boards.data ?? []
  const at = list.findIndex(b => b.id === menu.id)
  const shift = (d: -1 | 1) => {
    const ids = list.map(b => b.id)
    ;[ids[at], ids[at + d]] = [ids[at + d], ids[at]]
    boards.order.mutate(ids, { onError: () => toast.error("순서를 바꾸지 못했습니다.") })
  }
  const rename = () => {
    const label = name.trim()
    if (!label) return
    boards.update.mutate({ id: menu.id, label }, { onError: () => toast.error("이름을 바꾸지 못했습니다.") })
    setRenaming(false)
  }
  const remove = () => {
    boards.remove.mutate(menu.id, {
      onSuccess: () => { toast.success(`'${menu.label}' 메뉴를 지웠어요.`); navigate("/home", { replace: true }) },
      onError: () => toast.error("메뉴를 지우지 못했습니다."),
    })
    setDeleting(false)
  }
  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 text-xs"><MoreHorizontal className="size-3.5" />메뉴 설정</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onSelect={() => { setName(menu.label); setRenaming(true) }}><Pencil />이름 바꾸기</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setDuplicating(true)}><Copy />복제해서 새 메뉴</DropdownMenuItem>
        <DropdownMenuItem disabled={at <= 0} onSelect={() => shift(-1)}><ChevronLeft />왼쪽으로</DropdownMenuItem>
        <DropdownMenuItem disabled={at < 0 || at >= list.length - 1} onSelect={() => shift(1)}><ChevronRight />오른쪽으로</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(true)}><Trash2 />메뉴 삭제</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>

    <Dialog open={renaming} onOpenChange={setRenaming}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>메뉴 이름 바꾸기</DialogTitle>
          <DialogDescription>홈 위 탭에 보일 이름이에요.</DialogDescription>
        </DialogHeader>
        <Input autoFocus value={name} maxLength={30} onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === "Enter") rename() }} />
        <DialogFooter>
          <Button variant="outline" onClick={() => setRenaming(false)}>취소</Button>
          <Button disabled={!name.trim()} onClick={rename}>저장</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <NewBoardDialog open={duplicating} onOpenChange={setDuplicating} duplicateOf={menu} />

    <AlertDialog open={deleting} onOpenChange={setDeleting}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>'{menu.label}' 메뉴를 삭제할까요?</AlertDialogTitle>
          <AlertDialogDescription>이 메뉴의 위젯 배치가 지워져요. 이 메뉴에만 있던 종목 추적 위젯은 추적·알림도 멈춰요.</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>취소</AlertDialogCancel>
          <AlertDialogAction onClick={remove}>삭제</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </>
}

function WidgetItem({ defId, w, fine, params, onRemove, onOpen }: { defId: string; w: number; fine: number; params?: Record<string, unknown>; onRemove: () => void; onOpen?: () => void }) {
  const def = WIDGET_BY_ID[defId]
  const meta = def.useMeta(params)
  const h = coarseH(fine)
  return (
    <WidgetFrame title={def.titleOf?.(params) ?? def.title} asOf={meta.asOf} stale={meta.stale} detailPath={def.detailPathOf?.(params) ?? def.detailPath}
      onRemove={onRemove} onOpen={onOpen} flat={def.flat && h <= 1}>
      <def.Body w={w} h={h} params={params} />
    </WidgetFrame>
  )
}
