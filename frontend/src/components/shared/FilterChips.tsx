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
      className="flex w-auto flex-wrap gap-1.5 bg-transparent p-0"
    >
      {options.map((opt) => (
        <ToggleGroupItem
          key={opt.value}
          value={opt.value}
          className={cn(
            // 시안 칩: 선 알약, 선택 = 글자색 채움
            "h-7 rounded-full border border-line-2 px-3 text-xs text-ink-2 shadow-none",
            "data-[state=on]:border-action data-[state=on]:bg-action data-[state=on]:font-medium data-[state=on]:text-action-ink data-[state=on]:shadow-none data-[state=on]:hover:bg-action/85"
          )}
        >
          {opt.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
