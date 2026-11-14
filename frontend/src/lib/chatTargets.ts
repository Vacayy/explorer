import type { AttachmentRef, ChatTarget, ChatTargetKind } from "@/types"
import { formatKstSlashDate } from "@/utils/format"

/** AI 대화 › 대상 붙이기 규칙 (ia-redesign §4.14a, D-311) — 화면과 무관한 순수 함수 */

/** 한 번에 붙일 수 있는 대상 수(시안 '5개까지'). 서버도 같은 수를 넘으면 422 */
export const MAX_TARGETS = 5

/** 종류 칩 순서와 이름 — 시안 6개(전체·종목·미국·서사·질문·자료) + D-311로 더한 인물·테마·Peer·리포트 */
export const TARGET_KINDS: { kind: ChatTargetKind | null; label: string }[] = [
  { kind: null, label: "전체" }, { kind: "stock", label: "종목" }, { kind: "us_stock", label: "미국" },
  { kind: "narrative", label: "서사" }, { kind: "question", label: "질문" }, { kind: "doc", label: "자료" },
  { kind: "person", label: "인물" }, { kind: "theme", label: "테마" }, { kind: "peer_group", label: "Peer" },
  { kind: "report", label: "리포트" },
]

/** 묶음 머리·칩 앞 글자 */
export const KIND_NAME: Record<ChatTargetKind, string> = {
  stock: "종목", us_stock: "미국", narrative: "서사", question: "질문", doc: "자료",
  person: "인물", theme: "테마·업종", peer_group: "Peer 그룹", report: "리포트",
}

export const sameTarget = (a: AttachmentRef, b: AttachmentRef) => a.kind === b.kind && a.ref === b.ref

/** 대상을 붙인다 — 같은 대상은 한 번, 보낼 수 있는 것이 MAX_TARGETS개면 더 붙이지 않는다(그대로 돌려준다) */
export function addTarget(list: ChatTarget[], t: ChatTarget): ChatTarget[] {
  if (list.some(x => sameTarget(x, t))) return list
  if (sendable(list).length >= MAX_TARGETS) return list
  return [...list, t]
}

/** 보낼 대상 — 사라진(available=false) 칩은 뺀다 */
export const sendable = (list: ChatTarget[]) => list.filter(t => t.available !== false)

/** 요청 본문 모양 {kind, ref, label} */
export const toPayload = (list: ChatTarget[]): AttachmentRef[] => sendable(list).map(({ kind, ref, label }) => ({ kind, ref, label }))

/**
 * 커서 앞 글에서 `@검색어`를 찾는다. 줄 처음이나 공백 뒤의 `@`만 본다(메일 주소 'a@b'는 무시).
 * 반환: { start: '@' 위치, query } 또는 null
 */
export function findAtQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret)
  const m = before.match(/(^|\s)@([^\s@]{0,30})$/)
  if (!m) return null
  return { start: before.length - m[2].length - 1, query: m[2] }
}

/** 고른 뒤 입력 글에서 `@검색어`를 지운다(글 속에 토큰을 섞지 않는다) */
export function removeAtQuery(text: string, at: { start: number; query: string }): string {
  return text.slice(0, at.start) + text.slice(at.start + 1 + at.query.length)
}

/** 칩 뒤쪽 보조 정보 — 종목은 코드, 서사·자료·리포트는 날짜(MM/DD), 질문은 번호 */
export function chipMeta(t: ChatTarget): string | null {
  if (t.kind === "stock" || t.kind === "us_stock") return t.code ?? t.ref
  if (t.kind === "question") return t.code ?? `#${t.ref}`
  if ((t.kind === "narrative" || t.kind === "doc" || t.kind === "report") && t.date) return formatKstSlashDate(t.date, false)
  return null
}
