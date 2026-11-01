/** 옴니바(⌘K) 열기 — Omnibar가 document keydown을 듣는다 */
export function openOmnibar() {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
}
