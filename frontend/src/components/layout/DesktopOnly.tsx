import { useEffect, useState, type ReactNode } from "react"
import { Monitor } from "lucide-react"

const QUERY = "(min-width: 1024px)"

/** 데스크톱 전용 — 폭 <1024px이면 앱 대신 안내만 (docs/specs/app-shell.md §6) */
export function DesktopOnly({ children }: { children: ReactNode }) {
  const [wide, setWide] = useState(() => typeof window === "undefined" || window.matchMedia(QUERY).matches)
  useEffect(() => {
    const mq = window.matchMedia(QUERY)
    const on = () => setWide(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  if (wide) return <>{children}</>
  return (
    <main className="grid min-h-dvh place-items-center bg-background px-6">
      <div className="max-w-sm space-y-3 text-center">
        <Monitor className="mx-auto size-8 text-muted-foreground" aria-hidden />
        <h1 className="text-lg font-semibold">데스크톱에서 열어 주세요</h1>
        <p className="text-sm text-muted-foreground">Explorer는 1024px 이상 화면에서 씁니다. 텔레그램 브리핑과 봇은 휴대폰에서도 그대로 받습니다.</p>
      </div>
    </main>
  )
}
