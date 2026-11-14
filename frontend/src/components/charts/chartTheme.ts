import { useEffect, useState } from "react"
import { ColorType } from "lightweight-charts"
import type { ChartOptions, DeepPartial } from "lightweight-charts"

/**
 * 차트 색 — index.css 토큰에서 읽는다 (D-320: 시리즈 회색 · 선택 글자색 · 등락 토큰).
 * 테마를 바꾸면 useChartTheme()가 새 값을 돌려주므로, 차트는 그때 applyOptions로 다시 칠한다.
 */
export interface ChartTheme {
  ink: string
  ink2: string
  ink3: string
  line: string
  grid: string
  series: string
  up: string
  down: string
  hyp: string
  bg: string
}

function token(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  return styles.getPropertyValue(name).trim() || fallback
}

export function readChartTheme(): ChartTheme {
  const s = getComputedStyle(document.documentElement)
  return {
    ink: token(s, "--ink", "#0E1A22"),
    ink2: token(s, "--ink-2", "#46555F"),
    ink3: token(s, "--ink-3", "#5F6F7A"),
    line: token(s, "--line", "rgba(14,26,34,.1)"),
    grid: token(s, "--grid", "rgba(14,26,34,.07)"),
    series: token(s, "--series", "rgba(14,26,34,.26)"),
    up: token(s, "--up", "#D83995"),
    down: token(s, "--down", "#0593C6"),
    hyp: token(s, "--hyp", "#6E46CF"),
    bg: token(s, "--bg", "#FCFFFF"),
  }
}

/** <html>의 .dark가 바뀔 때마다 새 차트 색을 돌려준다 */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState(readChartTheme)
  useEffect(() => {
    const root = document.documentElement
    let last = root.classList.contains("dark")
    const observer = new MutationObserver(() => {
      const dark = root.classList.contains("dark")
      if (dark !== last) { last = dark; setTheme(readChartTheme()) }
    })
    observer.observe(root, { attributes: true, attributeFilter: ["class"] })
    return () => observer.disconnect()
  }, [])
  return theme
}

/** lightweight-charts 공통 옵션 — 배경 투명, 축 글자 ink-3, 격자 --grid, 경계 --line */
export function chartOptions(t: ChartTheme): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: t.ink3,
      fontFamily: "'Geist Mono', 'IBM Plex Sans KR', ui-monospace, monospace",
    },
    grid: {
      vertLines: { color: t.grid },
      horzLines: { color: t.grid },
    },
    crosshair: {
      vertLine: { color: t.series, labelBackgroundColor: t.ink2 },
      horzLine: { color: t.series, labelBackgroundColor: t.ink2 },
    },
    timeScale: { borderColor: t.line },
    rightPriceScale: { borderColor: t.line },
    leftPriceScale: { borderColor: t.line },
  }
}
