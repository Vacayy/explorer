import { useEffect, useRef, useState, type ComponentType } from "react"
import { Button } from "@/components/ui/button"
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover"

const MAX_SELECTED = 500     // 지목 문장 상한
const MAX_BLOCK = 1200       // 문단 맥락 상한
const BLOCK_TAGS = new Set(["P", "LI", "TD", "TH", "BLOCKQUOTE", "H1", "H2", "H3", "H4", "PRE"])

/** 마우스를 뗀 순간의 선택 — 버튼을 누르는 동안 브라우저 선택이 풀려도 이 값으로 동작한다 */
export interface TextSelection {
  /** 선택 문장 (정리된 텍스트, 상한 500자) */
  selected: string
  /** 선택이 속한 문단 전체 (상한 1,200자) */
  block: string
  /** 선택 범위 사본과 문단 요소 — 화면별 추가 정보(근거 번호·본문 오프셋)를 뽑을 때 */
  range: Range
  blockEl: Element | null
}

export interface SelectionAction {
  key: string
  label: string
  Icon: ComponentType<{ className?: string }>
  onSelect: (sel: TextSelection) => void
  /** 주 동작(AI에게 묻기)은 채운 버튼 */
  primary?: boolean
}

/** 선택 텍스트 정리 — ignore 선택자(예: 근거 칩)는 걷어낸다. 칩 숫자가 붙으면 "급증했다4."가 된다 */
function cleanText(node: Node, ignore?: string): string {
  const el = document.createElement("div")
  el.appendChild(node.cloneNode(true))
  if (ignore) el.querySelectorAll(ignore).forEach(n => n.remove())
  return (el.textContent || "").replace(/[ \t]+/g, " ").trim()
}

/** 선택 지점에서 가장 가까운 문단 — 블록 태그 또는 data-selection-block */
function blockOf(node: Node | null, root: HTMLElement): Element | null {
  let el: Node | null = node
  while (el && el !== root) {
    if (el.nodeType === 1 && (BLOCK_TAGS.has((el as Element).tagName) || (el as Element).hasAttribute("data-selection-block"))) return el as Element
    el = el.parentNode
  }
  return null
}

/** 줄글(pre-wrap) 본문은 문단 요소가 없다 — 선택이 든 텍스트 노드에서 빈 줄로 나뉜 문단을 잘라 온다 */
function paragraphAround(range: Range): string | null {
  const node = range.startContainer
  if (node.nodeType !== 3 || node !== range.endContainer) return null
  const text = node.textContent || ""
  const start = text.lastIndexOf("\n\n", range.startOffset)
  const end = text.indexOf("\n\n", range.endOffset)
  return text.slice(start < 0 ? 0 : start + 2, end < 0 ? text.length : end).replace(/[ \t]+/g, " ").trim() || null
}

/**
 * 공통 선택 팔레트 (docs/specs/canvas.md §2) — 컨테이너 안에서 텍스트를 고르면 선택 위에 동작 버튼이 뜬다.
 * 문서 읽기·스터디·대화 답변이 같은 부품을 쓰고, 화면마다 지원하는 동작만 넘긴다(하이라이트·설명·검토·스터디에 담기·AI에게 묻기).
 * 마우스를 뗀 시점에만 평가한다 — 드래그 중에 따라다니면 선택을 방해한다. 위치는 shadcn Popover의 가상 기준점.
 */
export function SelectionPalette({ containerRef, actions, enabled = true, ignore }: {
  containerRef: React.RefObject<HTMLElement | null>
  actions: SelectionAction[]
  /** false면 뜨지 않는다(예: 스터디에서 도구 모드가 '읽기'가 아닐 때) */
  enabled?: boolean
  /** 선택 텍스트에서 뺄 요소 선택자 */
  ignore?: string
}) {
  const [sel, setSel] = useState<TextSelection | null>(null)
  const rect = useRef<DOMRect>(new DOMRect())
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!enabled) { setSel(null); return }
    const onUp = (e: MouseEvent) => {
      if (contentRef.current?.contains(e.target as Node)) return   // 팔레트 버튼 클릭
      const root = containerRef.current
      const s = window.getSelection()
      if (!root || !s || s.rangeCount === 0 || !s.toString().trim() || !root.contains(s.anchorNode) || !root.contains(s.focusNode)) {
        setSel(null); return
      }
      const range = s.getRangeAt(0).cloneRange()
      const selected = cleanText(range.cloneContents(), ignore)
      if (!selected) { setSel(null); return }
      const blockEl = blockOf(range.commonAncestorContainer, root) ?? blockOf(s.anchorNode, root)
      rect.current = range.getBoundingClientRect()
      const block = blockEl ? cleanText(blockEl, ignore) : paragraphAround(range) ?? selected
      setSel({ selected: selected.slice(0, MAX_SELECTED), block: block.slice(0, MAX_BLOCK), range, blockEl })
    }
    document.addEventListener("mouseup", onUp)
    return () => document.removeEventListener("mouseup", onUp)
  }, [containerRef, enabled, ignore])

  const close = () => setSel(null)
  return (
    <Popover open={!!sel} onOpenChange={open => { if (!open) close() }}>
      <PopoverAnchor virtualRef={{ current: { getBoundingClientRect: () => rect.current } }} />
      <PopoverContent ref={contentRef} side="top" align="center" sideOffset={6} role="toolbar" aria-label="선택한 문장으로 할 일"
        className="flex w-auto flex-row items-center gap-0.5 rounded-lg p-1 shadow-md"
        onOpenAutoFocus={e => e.preventDefault()} onCloseAutoFocus={e => e.preventDefault()}
        // 버튼을 눌러도 화면의 선택 표시가 남게
        onPointerDown={e => e.preventDefault()}>
        {actions.map(a => (
          <Button key={a.key} size="sm" variant={a.primary ? "default" : "ghost"} className="h-7 gap-1 px-2 text-xs"
            onClick={() => { if (sel) a.onSelect(sel); close(); window.getSelection()?.removeAllRanges() }}>
            <a.Icon className="size-3.5" />{a.label}
          </Button>
        ))}
      </PopoverContent>
    </Popover>
  )
}
