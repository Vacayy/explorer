import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

interface Option {
  value: string
  label: string
}

interface Props {
  value: string
  onChange: (value: string) => void
  options?: Option[]
}

const DEFAULT_OPTIONS: Option[] = [
  { value: "quarterly", label: "분기" },
  { value: "annual", label: "연도" },
  { value: "trailing", label: "4분기누적" },
]

/** Period toggle — Radix ToggleGroup(single) 래핑, iOS 세그먼트 스타일 (docs/DESIGN_SYSTEM.md §3) */
export default function PeriodToggle({ value, onChange, options = DEFAULT_OPTIONS }: Props) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v)}
      className="inline-flex rounded-lg bg-secondary p-0.5 gap-0.5"
    >
      {options.map((opt) => (
        <ToggleGroupItem
          key={opt.value}
          value={opt.value}
          className={cn(
            "h-7 px-3 text-xs rounded-md text-muted-foreground hover:bg-transparent hover:text-muted-foreground",
            "data-[state=on]:bg-card data-[state=on]:text-foreground data-[state=on]:shadow-sm data-[state=on]:hover:bg-card"
          )}
        >
          {opt.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
