import { useState, type ReactNode } from 'react'
import { ArrowLeft, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { PageLayout, PageHeader } from './PageLayout'
import { useDetailBack } from './DetailNavigation'

export function DetailLayout({ title, context, actions, navigation, aside, related, children, fallback = '/home', backLabel = 'Home으로 돌아가기' }: {
  title: ReactNode; context?: ReactNode; actions?: ReactNode; navigation?: ReactNode; aside?: ReactNode; related?: ReactNode; children: ReactNode; fallback?: string; backLabel?: string
}) {
  const back = useDetailBack(fallback, backLabel)
  return <PageLayout><div className="detail-surface">
    <div className="detail-topbar"><Button variant="ghost" size="sm" onClick={back.go}><ArrowLeft aria-hidden="true" />{back.label}</Button><div className="flex flex-wrap items-center gap-2">{actions}</div></div>
    <div className="detail-grid" data-aside={!!aside}>
      <article className="min-w-0"><div className="mb-3 flex flex-wrap items-center gap-2 text-caption text-muted-foreground">{context}</div><PageHeader title={title} />
        {navigation && <div className="detail-navigation">{navigation}</div>}
        <div className="detail-body">{children}</div>
        {related && <footer className="mt-6 space-y-4 border-t pt-5">{related}</footer>}
      </article>
      {aside && <aside className="detail-aside" aria-label="상세 맥락">{aside}</aside>}
    </div>
  </div></PageLayout>
}
export function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return <Collapsible open={open} onOpenChange={setOpen} className="border-t py-3">
    <CollapsibleTrigger asChild><Button variant="ghost" className="h-auto w-full justify-between whitespace-normal px-0 text-left font-semibold">{title}<ChevronDown aria-hidden="true" className={open ? 'rotate-180' : ''} /></Button></CollapsibleTrigger>
    <CollapsibleContent className="space-y-3 pt-3">{children}</CollapsibleContent>
  </Collapsible>
}
