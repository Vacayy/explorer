import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

interface Props {
  value: number
  onChange: (years: number) => void
  options?: number[]
}

/** Year range toggle — Radix ToggleGroup(single) 래핑 (docs/DESIGN_SYSTEM.md §3) */
export default function YearToggle({ value, onChange, options = [5, 10] }: Props) {
  return (
    <ToggleGroup
      type="single"
      value={String(value)}
      onValueChange={(v) => v && onChange(Number(v))}
      spacing={1}
      className="inline-flex"
    >
      {options.map((y) => (
        <ToggleGroupItem
          key={y}
          value={String(y)}
          className={cn(
            "h-8 px-3 text-sm rounded-lg text-muted-foreground",
            "data-[state=on]:border data-[state=on]:border-primary data-[state=on]:text-primary data-[state=on]:bg-accent data-[state=on]:hover:bg-accent"
          )}
        >
          {y}년
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
