/**
 * Droplet reveal(물방울 등장) — 패널 안에서 더 볼 내용을 바닥부터 퍼지듯 펼친다 (docs/DESIGN_SYSTEM.md '모션').
 *
 * 공식 shadcn Collapsible(Radix) 위의 조합이라 열림 상태·키보드·aria-expanded는 Radix가 맡는다.
 * 감싼 패널(DropletReveal)이 기준 상자가 되고, 펼침 내용(DropletContent)은 패널을 덮어 패널 높이를 바꾸지 않는다
 * — 옆 패널과 높이를 맞춘 레이아웃(홈 Market Overnight·Today)에서도 쓸 수 있다.
 *
 *   <DropletReveal className="p-5">
 *     …요약…
 *     <DropletTrigger asChild><Button variant="outline">브리핑 전체 보기</Button></DropletTrigger>
 *     <DropletContent title="브리핑 전체" description="어젯밤 미국장">…본문…</DropletContent>
 *   </DropletReveal>
 */
import type { ComponentProps, ReactNode } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"

/** 펼침 내용의 기준 상자 — 패널 자체에 쓴다 */
export function DropletReveal({ className, ...props }: ComponentProps<typeof Collapsible>) {
  return <Collapsible className={cn("relative overflow-hidden", className)} {...props} />
}

export const DropletTrigger = CollapsibleTrigger

/** 패널을 덮으며 물방울처럼 퍼지는 펼침 내용. 머리(제목·닫기)는 고정, 본문은 안에서 스크롤 */
export function DropletContent({ title, description, children, className }: {
  title: ReactNode; description?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <CollapsibleContent
      className={cn("absolute inset-0 z-10 flex flex-col rounded-[inherit] bg-[color-mix(in_srgb,var(--surface)_94%,transparent)] backdrop-blur-xl animate-droplet", className)}>
      <div className="flex min-h-0 flex-1 flex-col gap-3.5 px-[22px] py-5 animate-droplet-rise max-sm:px-4">
        <div className="flex items-center justify-between gap-2.5">
          <div className="flex min-w-0 flex-col gap-0.5">
            <p className="font-display text-xl">{title}</p>
            {description && <p className="text-xs text-ink-2">{description}</p>}
          </div>
          <CollapsibleTrigger asChild>
            <Button variant="outline" size="icon" aria-label="닫기" className="size-9 shrink-0 rounded-full bg-surface"><X aria-hidden="true" /></Button>
          </CollapsibleTrigger>
        </div>
        <div className="-mr-1 min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">{children}</div>
      </div>
    </CollapsibleContent>
  )
}
