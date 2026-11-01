/** 셸 패널 열림·대화 패널 스레드 — 화면 상태가 아니라 사용자 편의라 localStorage (docs/specs/app-shell.md §1). 실패하면 기본값. */
export function readPref(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
export function writePref(key: string, value: string | null) {
  try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value) } catch { /* private storage */ }
}
export const PREF = { left: "explorer.shell.left", ai: "explorer.shell.ai", thread: "explorer.shell.thread", group: "explorer.shell.group" } as const

/** 대화 패널이 지금 보고 있는 스레드 — 답변 도착 토스트를 중복으로 띄우지 않기 위해 AnswerWatcher가 읽는다 */
let panelThread: number | null = null
export const setPanelThread = (id: number | null) => { panelThread = id }
export const getPanelThread = () => panelThread
