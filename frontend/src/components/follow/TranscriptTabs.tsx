import { useNavigate } from "react-router-dom"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

/** 탐색 › 컨콜의 하위 보기 — 컨콜(기업 목록·콜 상세)·실적 시즌은 ?view=. 옛 미국 기업 목록(/us)은 컨콜로 리다이렉트(ia-redesign §10.6).
 * 옛 프록시 보기(?view=proxies)는 Thesis › 내 판단 '지표 보드'(/questions?view=proxies)로 옮겼다(4f단계, TranscriptPage가 리다이렉트). */
const VIEWS = [
  { key: "calls", label: "컨콜", path: "/follow/transcripts" },
  { key: "season", label: "실적 시즌", path: "/follow/transcripts?view=season" },
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
