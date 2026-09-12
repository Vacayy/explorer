import { useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MODES } from "@/components/layout/navConfig"
import { openOmnibar } from "@/components/layout/Dock"

/**
 * 전역 단축키 — `/` 옴니바 · ⌥1~4 모드 이동(Home·관심목록·월드모델·대화). ⌘K는 Omnibar, ⌘B는 Sidebar가 직접 듣는다.
 * ⌘1~9는 브라우저가 탭 전환으로 선점해 페이지에서 가로챌 수 없어 ⌥(Option)을 쓴다.
 */
export function useKeyboardShortcuts() {
  const navigate = useNavigate()

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      // Don't trigger when typing in inputs
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return

      if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault()
        openOmnibar()
        return
      }
      if (e.altKey && !e.metaKey && !e.ctrlKey && /^Digit[1-5]$/.test(e.code)) {
        const mode = MODES[Number(e.code.slice(5)) - 1]
        if (mode) { e.preventDefault(); navigate(mode.path) }
      }
    }

    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [navigate])
}
