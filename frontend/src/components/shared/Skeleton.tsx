import { Skeleton } from "@/components/ui/skeleton"

// Re-export official shadcn Skeleton
export { Skeleton }

export function KpiSkeleton() {
  return (
    <div className="grid grid-cols-6 gap-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="border rounded-lg p-4 text-center space-y-2">
          <Skeleton className="h-3 w-16 mx-auto" />
          <Skeleton className="h-6 w-20 mx-auto" />
          <Skeleton className="h-3 w-12 mx-auto" />
        </div>
      ))}
    </div>
  )
}

export function ChartSkeleton({ height = 300 }: { height?: number }) {
  return (
    <div className="border rounded-lg p-5 space-y-3">
      <Skeleton className="h-4 w-40" />
      <Skeleton style={{ height }} className="w-full" />
    </div>
  )
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      <Skeleton className="h-10 w-full" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  )
}
