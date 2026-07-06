import { Badge } from "@/components/ui/badge"

const SOURCE_LABEL: Record<string, string> = {
  telegram: "텔레그램",
  blog: "블로그",
  dart: "공시",
  report: "리포트",
}

export function SourceBadge({ sourceType }: { sourceType: string }) {
  return (
    <Badge variant="secondary" className="text-[11px] font-normal">
      {SOURCE_LABEL[sourceType] ?? sourceType}
    </Badge>
  )
}
