import { Button } from "@/components/ui/button"
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

/** Segmented tab bar — wraps shadcn Button for inline tab switching */
export default function SegmentTabs({ tabs, value, onChange, className }: Props) {
  return (
    <div className={cn("inline-flex border rounded-lg overflow-hidden", className)}>
      {tabs.map((tab) => (
        <Button
          key={tab.value}
          variant="ghost"
          size="sm"
          onClick={() => onChange(tab.value)}
          className={cn(
            "rounded-none border-0 h-8 px-4 text-[13px]",
            value === tab.value
              ? "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
              : "text-secondary-foreground hover:bg-secondary"
          )}
        >
          {tab.label}
        </Button>
      ))}
    </div>
  )
}
