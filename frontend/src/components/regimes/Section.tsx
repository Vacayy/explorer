import type { ReactNode } from "react"
import { BookOpen } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/** 섹션 머리 + '읽는 법' — 투자자가 숫자 전에 무엇을 보는지부터 알게 */
export function Section({ id, step, title, how, children }: { id: string; step: number; title: string; how: ReactNode; children: ReactNode }) {
  return <Card id={id} className="scroll-mt-24">
    <CardHeader className="space-y-2">
      <CardTitle className="flex items-baseline gap-2"><span className="text-caption tabular-nums text-muted-foreground">{step}</span>{title}</CardTitle>
      <div className="flex gap-2 rounded-lg bg-muted/50 px-3 py-2 text-caption leading-relaxed text-muted-foreground">
        <BookOpen className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /><div><span className="font-medium text-foreground">읽는 법 </span>{how}</div>
      </div>
    </CardHeader>
    <CardContent className="space-y-4">{children}</CardContent>
  </Card>
}
