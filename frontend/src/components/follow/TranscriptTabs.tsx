import { useNavigate } from "react-router-dom"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

/** 탐색 › 컨콜의 하위 보기 — 컨콜(기업 목록·콜 상세)·실적 시즌·프록시는 ?view=. 옛 미국 기업 목록(/us)은 컨콜로 리다이렉트(ia-redesign §10.6).
 * 프록시는 Thesis › 내 판단 '지표 보드'가 생길 때까지 남긴다(§10.3). */
const VIEWS = [
  { key: "calls", label: "컨콜", path: "/follow/transcripts" },
  { key: "season", label: "실적 시즌", path: "/follow/transcripts?view=season" },
  { key: "proxies", label: "프록시", path: "/follow/transcripts?view=proxies" },
] as const

export type TranscriptView = (typeof VIEWS)[number]["key"]

export function TranscriptTabs({ value }: { value: TranscriptView }) {
  const navigate = useNavigate()
  return (
    <Tabs value={value} onValueChange={(v) => navigate(VIEWS.find((x) => x.key === v)!.path, { replace: true })}>
      <TabsList>
        {VIEWS.map((v) => <TabsTrigger key={v.key} value={v.key}>{v.label}</TabsTrigger>)}
      </TabsList>
    </Tabs>
  )
}
