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
      spacing={0}
      className={cn("inline-flex border rounded-lg overflow-hidden", className)}
    >
      {tabs.map((tab) => (
        <ToggleGroupItem
          key={tab.value}
          value={tab.value}
          className={cn(
            "h-8 px-4 text-[13px] rounded-none first:rounded-l-none last:rounded-r-none border-0",
            "text-secondary-foreground hover:bg-secondary hover:text-secondary-foreground",
            "data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:hover:bg-primary/90"
          )}
        >
          {tab.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
