import { Button } from "@/components/ui/button"

interface Option {
  value: string
  label: string
}

interface Props {
  options: Option[]
  value: string
  onChange: (value: string) => void
}

/** Filter chip group — wraps shadcn Button for filter selection */
export default function FilterChips({ options, value, onChange }: Props) {
  return (
    <div className="flex gap-1.5 flex-wrap">
      {options.map((opt) => (
        <Button
          key={opt.value}
          variant={value === opt.value ? "outline" : "ghost"}
          size="sm"
          onClick={() => onChange(opt.value)}
          className={
            value === opt.value
              ? "border-primary text-primary bg-accent h-7 text-xs"
              : "text-muted-foreground h-7 text-xs"
          }
        >
          {opt.label}
        </Button>
      ))}
    </div>
  )
}
