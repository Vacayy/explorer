import { useEffect, useState, type RefObject } from "react"

/** 요소의 현재 픽셀 크기 — react-force-graph는 부모에 자동 맞춤이 없어 width/height를 직접 넘겨야 한다. */
export function useElementSize(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return size
}
