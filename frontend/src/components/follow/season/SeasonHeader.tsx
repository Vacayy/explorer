// 실적 시즌 머리 — 시즌 이름 · 시장 `미국 | 한국` · 시즌 선택(이전·목록·다음). 두 시장이 같이 쓴다(ia-redesign §4.6·§4.22).
// URL: market(kr이면 한국, 없으면 미국) · season. 시장·시즌을 바꾸면 그 화면 안의 고른 값(날짜·탭 등)은 지운다.
import type { ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { seasonNeighbors } from "@/lib/seasonBoard"

export type SeasonMarket = "us" | "kr"
export const seasonMarket = (p: URLSearchParams): SeasonMarket => (p.get("market") === "kr" ? "kr" : "us")

/** 시즌·시장을 바꿀 때 지우는 화면 안 값 */
const LOCAL_KEYS = ["sector", "day", "pick", "rtab", "core", "kf", "kp"]
const shortSeason = (key: string) => `${key.slice(0, 4)} Q${key.slice(-1)}`

export function MarketToggle() {
  const [params, setParams] = useSearchParams()
  const market = seasonMarket(params)
  return (
    <SegmentTabs value={market} tabs={[{ value: "us", label: "미국" }, { value: "kr", label: "한국" }]}
      onChange={(v) => setParams((p) => {
        const n = new URLSearchParams(p)
        if (v === "kr") n.set("market", "kr"); else n.delete("market")
        for (const k of LOCAL_KEYS) n.delete(k)
        return n
      })} />
  )
}

/** 시즌 선택 — options는 오래된 순 키. 고르면 season을 바꾸고 화면 안 값은 지운다 */
export function SeasonPicker({ options, value, currentKey }: { options: string[]; value: string; currentKey: string | null }) {
  const [, setParams] = useSearchParams()
  const keys = options.includes(value) ? options : [...options, value].sort()
  const { prev, next } = seasonNeighbors(keys, value)
  const pick = (key: string | null) => {
    if (!key) return
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set("season", key)
      for (const k of LOCAL_KEYS) n.delete(k)
      return n
    })
  }
  return (
    <div className="flex items-center gap-1">
      <Button variant="outline" size="icon-sm" aria-label="이전 시즌" disabled={!prev} onClick={() => pick(prev)}><ChevronLeft /></Button>
      <Select value={value} onValueChange={pick}>
        <SelectTrigger className="w-44" aria-label="시즌 선택"><SelectValue /></SelectTrigger>
        <SelectContent>
          {[...keys].reverse().map((k) => <SelectItem key={k} value={k}>{shortSeason(k)}{k === currentKey ? " · 진행 중" : ""}</SelectItem>)}
        </SelectContent>
      </Select>
      <Button variant="outline" size="icon-sm" aria-label="다음 시즌" disabled={!next} onClick={() => pick(next)}><ChevronRight /></Button>
    </div>
  )
}

/** 머리 한 줄 — 왼쪽 제목·부제, 오른쪽 시장 토글 + 시즌 선택(picker가 없으면 토글만) */
export function SeasonHeader({ title, sub, picker }: { title: ReactNode; sub?: ReactNode; picker?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-display text-page font-normal tracking-[-0.02em] max-md:text-[26px] max-md:leading-[1.3]">{title}</h1>
        {sub && <p className="text-caption text-muted-foreground">{sub}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <MarketToggle />
        {picker}
      </div>
    </div>
  )
}
