import type { ReactNode } from "react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface Props {
  title?: string
  headerRight?: ReactNode
  subtitle?: string
  children: ReactNode
  className?: string
}

/** Chart wrapper card — wraps shadcn Card for consistent chart container styling */
export default function ChartCard({ title, headerRight, subtitle, children, className }: Props) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      {(title || headerRight) && (
        <CardHeader className="flex flex-wrap items-center justify-between space-y-0">
          <div>
            {title && <CardTitle>{title}</CardTitle>}
            {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
          </div>
          {headerRight}
        </CardHeader>
      )}
      <CardContent>{children}</CardContent>
    </Card>
  )
}
