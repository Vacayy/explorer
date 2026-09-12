import { useCallback, useEffect, useRef, useState } from "react"
import type { Citation } from "./citations"

const MAX_SELECTED = 500     // 지목 문장 상한
const MAX_BLOCK = 1200       // 문단 맥락 상한

/** 컴포저에 달리는 인용 — 선택 문장만이 아니라 맥락과 근거를 함께 나른다 (D-146) */
export interface Quote {
  message_id: number
  selected: string
  block: string
  citations: Citation[]
}

export interface QuotePopover {
  quote: Quote
  top: number
  left: number
}

const BLOCK_TAGS = new Set(["P", "LI", "TD", "TH", "BLOCKQUOTE", "H1", "H2", "H3", "H4", "PRE"])

/** 근거 칩을 걷어낸 순수 텍스트 — 칩의 DOM 텍스트는 숫자뿐이라 그냥 두면 "급증했다4."가 된다 */
function cleanText(node: Node): string {
  const el = document.createElement("div")
  el.appendChild(node.cloneNode(true))
  el.querySelectorAll("[data-cite-n]").forEach((n) => n.remove())
  return (el.textContent || "").replace(/[ \t]+/g, " ").trim()
}

/** 이 요소 안에 있는 근거 번호들 */
function citeNumbers(el: Element | null): number[] {
  if (!el) return []
  return [...el.querySelectorAll("[data-cite-n]")]
    .map((n) => Number(n.getAttribute("data-cite-n")))
    .filter((n) => Number.isFinite(n))
}

/** 선택 지점에서 가장 가까운 블록 요소 — 문단 맥락의 단위 */
function blockOf(node: Node | null, root: HTMLElement): Element | null {
  let el: Node | null = node
  while (el && el !== root) {
    if (el.nodeType === 1 && BLOCK_TAGS.has((el as Element).tagName)) return el as Element
    el = el.parentNode
  }
  return null
}

/**
 * 답변 드래그 → 인용 (D-145, 맥락 보강 D-146).
 * 마우스를 뗀 시점에만 평가한다 — 드래그 중에 버튼이 따라다니면 선택을 방해한다.
 */
export function useQuoteSelection(
  ref: React.RefObject<HTMLElement | null>,
  messageId: number,
  citations: Citation[] | null,
) {
  const [popover, setPopover] = useState<QuotePopover | null>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const clear = useCallback(() => setPopover(null), [])

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const onUp = (e: MouseEvent) => {
      if (popRef.current?.contains(e.target as Node)) return   // 버튼 클릭이면 선택 유지
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0 || !sel.toString().trim() || !el.contains(sel.anchorNode)) {
        setPopover(null)
        return
      }
      const range = sel.getRangeAt(0)
      const selected = cleanText(range.cloneContents())
      if (!selected) { setPopover(null); return }

      const blockEl = blockOf(range.commonAncestorContainer, el) ?? blockOf(sel.anchorNode, el)
      const block = blockEl ? cleanText(blockEl) : selected
      // 근거: 선택 안 + 그 문단 안 (문장 끝 칩이 선택에서 빠지는 경우가 많다)
      const nums = new Set([...citeNumbers(blockEl), ...citeNumbers(range.cloneContents() as unknown as Element)])
      const cites = (citations ?? []).filter((c) => nums.has(c.n))

      const rect = range.getBoundingClientRect()
      const box = el.getBoundingClientRect()
      setPopover({
        quote: {
          message_id: messageId,
          selected: selected.slice(0, MAX_SELECTED),
          block: block.slice(0, MAX_BLOCK),
          citations: cites,
        },
        top: rect.top - box.top - 38,
        left: Math.max(0, rect.left - box.left + rect.width / 2),
      })
    }

    document.addEventListener("mouseup", onUp)
    return () => document.removeEventListener("mouseup", onUp)
  }, [ref, messageId, citations])

  return { popover, popRef, clear }
}
