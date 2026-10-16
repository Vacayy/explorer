import { useNavigate } from "react-router-dom"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

/** 탐색 › 컨콜의 하위 보기 — 컨콜 브라우저·실적 모멘텀·프록시는 ?view=, 미국 기업 디렉토리는 /us (docs/specs/explore-core.md §3) */
const VIEWS = [
  { key: "calls", label: "컨콜", path: "/follow/transcripts" },
  { key: "momentum", label: "실적 모멘텀", path: "/follow/transcripts?view=momentum" },
  { key: "us", label: "미국 기업", path: "/us" },
  { key: "proxies", label: "프록시", path: "/follow/transcripts?view=proxies" },
] as const

export type TranscriptView = (typeof VIEWS)[number]["key"]

export function TranscriptTabs({ value }: { value: TranscriptView }) {
  const navigate = useNavigate()
  return (
    <Tabs value={value} onValueChange={(v) => navigate(VIEWS.find((x) => x.key === v)!.path, { replace: v !== "us" && value !== "us" })}>
      <TabsList>
        {VIEWS.map((v) => <TabsTrigger key={v.key} value={v.key}>{v.label}</TabsTrigger>)}
      </TabsList>
    </Tabs>
  )
}
