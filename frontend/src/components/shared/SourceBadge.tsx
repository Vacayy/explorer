import { Badge } from "@/components/ui/badge"

const SOURCE_LABEL: Record<string, string> = {
  telegram: "텔레그램",
  blog: "블로그",
  youtube: "유튜브",
  dart: "공시",
  report: "리포트",
  canon: "역사",
  note: "노트",
  scrap: "스크랩 · 미검증",
  transcript: "컨콜",
  memo: "투자자 메모",
}

// 미검증 소스(개인 투자자 블로그 스크랩)는 가설 색으로 — 사실 소스와 눈으로 구분된다 (D-142)
const UNVERIFIED = new Set(["scrap"])

export function SourceBadge({ sourceType }: { sourceType: string }) {
  const unverified = UNVERIFIED.has(sourceType)
  return (
    <Badge variant={unverified ? "hyp" : "neutral"}>
      {SOURCE_LABEL[sourceType] ?? sourceType}
    </Badge>
  )
}
