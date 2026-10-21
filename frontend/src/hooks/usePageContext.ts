import { useLocation } from "react-router-dom"
import type { PageContext } from "@/api/spine"
import { SECTIONS, analyzeTabOf, locate } from "@/components/layout/navConfig"
import { useHomeBoards } from "@/hooks/useDashboard"

const ANALYZE_LABEL: Record<string, string> = { summary: "개요", financials: "실적·사업", mentions: "자료", lens: "렌즈" }

/** AI 대화 패널이 질문과 함께 보낼 '보고 있는 화면' (docs/specs/app-shell.md §5). 대화 화면 자체에서는 null */
export function usePageContext(companyName?: string | null): PageContext | null {
  const { pathname, search } = useLocation()
  const path = pathname + search
  const params = new URLSearchParams(search)
  const { data: homeBoards } = useHomeBoards()

  const kr = pathname.match(/^\/analyze\/([^/]+)/)
  if (kr && kr[1] !== "compare") {
    const tab = ANALYZE_LABEL[analyzeTabOf(pathname) ?? "summary"] ?? "개요"
    return { kind: "stock", ref: kr[1], path, label: `종목 ${companyName ?? kr[1]}(${kr[1]}) · ${tab}` }
  }
  const us = pathname.match(/^\/us\/([^/]+)/)
  if (us) return { kind: "us_stock", ref: us[1], path, label: `미국 종목 ${us[1]}` }
  const doc = pathname.match(/^\/doc\/(\d+)/)
  if (doc) return { kind: "doc", ref: doc[1], path, label: `문서 #${doc[1]}` }
  if (pathname.startsWith("/narrative") && params.get("topic")) {
    return { kind: "narrative", ref: params.get("topic")!, path, label: `서사 · ${params.get("topic")}` }
  }
  const q = pathname.match(/^\/question\/(\d+)/)
  if (q) return { kind: "question", ref: q[1], path, label: `질문 #${q[1]}` }
  if (pathname.startsWith("/chat")) return null

  const here = locate(pathname, search)
  if (!here) return null
  // 홈 L2는 내 메뉴(home_boards) — 탭 이름이 메뉴 이름이다
  const boardId = pathname.match(/^\/home\/b\/(\d+)/)?.[1]
  const menu = boardId ? homeBoards?.find(b => String(b.id) === boardId) : pathname === "/home" && here.section === "home" ? homeBoards?.[0] : undefined
  if (menu) return { kind: "page", path, label: `홈 · ${menu.label}` }
  const section = SECTIONS.find(s => s.key === here.section)!
  const tab = section.tabs.find(t => t.key === here.tab)!
  return { kind: "page", path, label: section.tabs.length > 1 ? `${section.label} · ${tab.label}` : section.label }
}
