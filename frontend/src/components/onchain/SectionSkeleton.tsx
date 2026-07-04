import { memo } from "react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"

export const SectionSkeleton = memo(function SectionSkeleton({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="animate-pulse space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-10 bg-muted rounded" />
          ))}
        </div>
      </CardContent>
    </Card>
  )
})

export const ErrorCard = memo(function ErrorCard({ title, message }: { title: string; message: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-sm text-muted-foreground">{message}</div>
      </CardContent>
    </Card>
  )
})
