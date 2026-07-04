import { Button } from "@/components/ui/button"

interface Props {
  value: number
  onChange: (years: number) => void
  options?: number[]
}

/** Year range toggle — wraps shadcn Button */
export default function YearToggle({ value, onChange, options = [5, 10] }: Props) {
  return (
    <div className="inline-flex gap-1">
      {options.map((y) => (
        <Button
          key={y}
          variant={value === y ? "outline" : "ghost"}
          size="sm"
          onClick={() => onChange(y)}
          className={value === y ? "border-primary text-primary bg-accent" : "text-muted-foreground"}
        >
          {y}년
        </Button>
      ))}
    </div>
  )
}
