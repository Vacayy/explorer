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
  className?: string
}

/** Filter chip group (단일선택) — Radix ToggleGroup(single) 래핑 (docs/DESIGN_SYSTEM.md §3) */
export default function FilterChips({ options, value, onChange, className }: Props) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v)}
      // 칩 사이 간격이 있는 묶음(spacing≠0)의 회색 바탕·안쪽 여백을 끈다 — 칩은 각자 선 알약
      className={cn("flex w-auto flex-wrap gap-1.5 not-data-[spacing=0]:bg-transparent not-data-[spacing=0]:p-0", className)}
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
