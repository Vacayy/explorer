import { useState, type ReactNode } from 'react'
import { ArrowLeft, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { PageLayout, PageHeader } from './PageLayout'
import { useDetailBack } from './DetailNavigation'

/**
 * 상세 화면 틀. 폰(<768)에서 `mobileTop`이 있으면 위 바의 버튼을 그것으로 줄이고,
 * `mobileBar`가 있으면 하단 탭 위에 행동 바로 고정한다(ia-redesign §4.32).
 */
export function DetailLayout({ title, context, actions, navigation, aside, related, children, fallback = '/home', backLabel = 'Home으로 돌아가기', mobileBackLabel, mobileTop, mobileBar }: {
  title: ReactNode; context?: ReactNode; actions?: ReactNode; navigation?: ReactNode; aside?: ReactNode; related?: ReactNode; children: ReactNode; fallback?: string; backLabel?: string
  mobileBackLabel?: string; mobileTop?: ReactNode; mobileBar?: ReactNode
}) {
  const back = useDetailBack(fallback, backLabel)
  return <PageLayout><div className="detail-surface">
    <div className="detail-topbar">
      <Button variant="ghost" size="sm" className="text-ink-2" onClick={back.go}><ArrowLeft aria-hidden="true" />{mobileBackLabel ? <><span className="max-md:hidden">{back.label}</span><span className="md:hidden">{mobileBackLabel}</span></> : back.label}</Button>
      <div className={mobileTop ? 'flex flex-wrap items-center gap-2 max-md:hidden' : 'flex flex-wrap items-center gap-2'}>{actions}</div>
      {mobileTop && <div className="flex items-center gap-2 md:hidden">{mobileTop}</div>}
    </div>
    <div className="detail-grid" data-aside={!!aside}>
      <article className="detail-article"><div className="mb-3.5 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-3">{context}</div><PageHeader title={title} />
        {navigation && <div className="detail-navigation">{navigation}</div>}
        <div className="detail-body">{children}</div>
        {related && <footer className="mt-6 space-y-4 border-t pt-5">{related}</footer>}
      </article>
      {aside && <aside className="detail-aside" aria-label="상세 맥락">{aside}</aside>}
    </div>
    {mobileBar && <>
      {/* 고정 바 높이만큼 본문 끝을 비운다 */}
      <div aria-hidden className="h-16 md:hidden" />
      <div className="fixed inset-x-0 bottom-[calc(var(--tabbar-height)+env(safe-area-inset-bottom))] z-30 grid grid-flow-col auto-cols-fr gap-2 border-t bg-background px-4 py-2 md:hidden">{mobileBar}</div>
    </>}
  </div></PageLayout>
}
export function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return <Collapsible open={open} onOpenChange={setOpen} className="border-t py-3">
    <CollapsibleTrigger asChild><Button variant="ghost" className="h-auto w-full justify-between whitespace-normal px-0 text-left font-semibold">{title}<ChevronDown aria-hidden="true" className={open ? 'rotate-180' : ''} /></Button></CollapsibleTrigger>
    <CollapsibleContent className="space-y-3 pt-3">{children}</CollapsibleContent>
  </Collapsible>
}
