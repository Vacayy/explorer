import { useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { SECTIONS } from "@/components/layout/navConfig"
import { openOmnibar } from "@/lib/omnibar"

/**
 * 전역 단축키 — `/` 옴니바 · ⌥1~5 L1 이동(홈·탐색·포트폴리오·캔버스·월드모델) · ⌘J AI 대화 패널.
 * ⌘K는 Omnibar, ⌘B는 내 목록(Sidebar)이 직접 듣는다 (docs/specs/app-shell.md §7).
 * ⌘1~9는 브라우저가 탭 전환으로 선점해 페이지에서 가로챌 수 없어 ⌥(Option)을 쓴다.
 */
export function useKeyboardShortcuts(toggleAi: () => void) {
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
        const section = SECTIONS[Number(e.code.slice(5)) - 1]
        if (section) { e.preventDefault(); navigate(section.path) }
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault()
        toggleAi()
      }
    }

    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [navigate, toggleAi])
}
