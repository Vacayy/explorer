import { Button } from "@/components/ui/button"
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

/** Period toggle button group — wraps shadcn Button for period selection */
export default function PeriodToggle({ value, onChange, options = DEFAULT_OPTIONS }: Props) {
  return (
    <div className="inline-flex rounded-lg bg-secondary p-0.5 gap-0.5">
      {options.map((opt) => (
        <Button
          key={opt.value}
          variant={value === opt.value ? "default" : "ghost"}
          size="sm"
          onClick={() => onChange(opt.value)}
          className={cn(
            "h-7 text-xs rounded-md",
            value === opt.value
              ? "bg-card text-foreground shadow-sm hover:bg-card"
              : "text-muted-foreground hover:bg-transparent"
          )}
        >
          {opt.label}
        </Button>
      ))}
    </div>
  )
}
