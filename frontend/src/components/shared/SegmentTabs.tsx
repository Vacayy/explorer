import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

interface Tab {
  value: string
  label: string
}

interface Props {
  tabs: Tab[]
  value: string
  onChange: (value: string) => void
  className?: string
}

/** Segmented tab bar — Radix ToggleGroup(single) 래핑 (docs/DESIGN_SYSTEM.md §3) */
export default function SegmentTabs({ tabs, value, onChange, className }: Props) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v)}
      spacing={1}
      className={cn("inline-flex max-w-full rounded-xl bg-muted/70 p-1", className)}
    >
      {tabs.map((tab) => (
        <ToggleGroupItem
          key={tab.value}
          value={tab.value}
          className={cn(
            "h-9 px-3 text-sm rounded-control border-0",
            "text-secondary-foreground hover:bg-secondary hover:text-secondary-foreground",
            "data-[state=on]:bg-card data-[state=on]:text-foreground data-[state=on]:shadow-sm data-[state=on]:hover:bg-card"
          )}
        >
          {tab.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
