import type { TextSelection } from "@/components/shared/SelectionPalette"
import type { Citation } from "./citations"

/** 컴포저에 달리는 인용 — 선택 문장만이 아니라 맥락과 근거를 함께 나른다 (D-146) */
export interface Quote {
  /** 답변에서 지목했을 때 (D-146) */
  message_id?: number
  /** 문서에서 지목했을 때 — 'AI에게 묻기' (docs/specs/canvas.md §2) */
  doc_id?: number
  doc_title?: string
  selected: string
  block: string
  citations: Citation[]
}

/** 근거 칩 선택자 — 선택 텍스트에서 걷어낸다 */
export const CITE_CHIP = "[data-cite-n]"

/** 이 노드 안에 있는 근거 번호들 */
function citeNumbers(el: ParentNode | null): number[] {
  if (!el) return []
  return [...el.querySelectorAll(CITE_CHIP)]
    .map(n => Number(n.getAttribute("data-cite-n")))
    .filter(n => Number.isFinite(n))
}

/**
 * 답변에서 고른 선택 → 인용 (D-145, 맥락 보강 D-146). 선택은 공통 선택 팔레트가 잡는다.
 * 근거: 선택 안 + 그 문단 안 (문장 끝 칩이 선택에서 빠지는 경우가 많다)
 */
export function quoteFromSelection(sel: TextSelection, messageId: number, citations: Citation[] | null): Quote {
  const nums = new Set([...citeNumbers(sel.blockEl), ...citeNumbers(sel.range.cloneContents())])
  return { message_id: messageId, selected: sel.selected, block: sel.block, citations: (citations ?? []).filter(c => nums.has(c.n)) }
}
