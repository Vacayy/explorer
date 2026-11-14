import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

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
      size="sm"
      className="inline-flex"
    >
      {options.map((opt) => (
        <ToggleGroupItem
          key={opt.value}
          value={opt.value}
          className="px-3"
        >
          {opt.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
