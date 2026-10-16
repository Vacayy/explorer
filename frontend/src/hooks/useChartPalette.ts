import { useEffect, useState } from "react"

/** 캔버스 차트는 CSS 변수를 못 읽는다 — 마운트 시 --chart-1..5 계산값으로 해석(라이트·다크 대응). */
export function useChartPalette(n: number, offset = 0) {
  const [colors, setColors] = useState<string[]>([])
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement)
    setColors(Array.from({ length: n }, (_, i) => cs.getPropertyValue(`--chart-${((i + offset) % 5) + 1}`).trim() || "#888"))
  }, [n, offset])
  return colors
}
