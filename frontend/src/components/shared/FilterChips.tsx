import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

interface Option {
  value: string
  label: string
}

interface Props {
  options: Option[]
  value: string
  onChange: (value: string) => void
}

/** Filter chip group (단일선택) — Radix ToggleGroup(single) 래핑 (docs/DESIGN_SYSTEM.md §3) */
export default function FilterChips({ options, value, onChange }: Props) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v)}
      className="flex flex-wrap gap-1.5 w-auto"
    >
      {options.map((opt) => (
        <ToggleGroupItem
          key={opt.value}
          value={opt.value}
          className={cn(
            "h-7 px-3 text-xs rounded-lg text-muted-foreground",
            "data-[state=on]:border data-[state=on]:border-primary data-[state=on]:text-primary data-[state=on]:bg-accent data-[state=on]:hover:bg-accent"
          )}
        >
          {opt.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
