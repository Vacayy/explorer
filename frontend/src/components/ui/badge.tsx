import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-[22px] w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-badge border border-transparent px-2 py-0 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        /* 등락·판정·인식론·상태를 한 모양으로 — 모서리 6, 높이 22 (DS-Components) */
        default: "bg-chip text-ink-2 [a]:hover:text-ink",
        secondary:
          "bg-chip text-ink-2 [a]:hover:text-ink",
        neutral: "bg-chip text-ink-2 [a]:hover:text-ink",
        up: "bg-up-tint text-up-ink",
        down: "bg-down-tint text-down-ink",
        hyp: "bg-hyp-tint text-hyp",
        fact: "bg-fact-tint text-fact",
        warn: "bg-warn-tint text-warn",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20",
        outline:
          "border-line-2 text-ink-2 [a]:hover:bg-chip [a]:hover:text-ink",
        accent: "bg-chip text-ink [a]:hover:text-ink-2",
        ghost:
          "text-ink-2 hover:bg-chip hover:text-ink",
        link: "text-ink underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
