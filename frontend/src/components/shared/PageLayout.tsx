import type { ReactNode, Ref } from 'react'
import { cn } from '@/lib/utils'
import SegmentTabs from './SegmentTabs'

interface PageLayoutProps {
  mode?: 'document' | 'workspace' | 'reader'
  width?: 'full' | 'reading'
  header?: ReactNode
  overview?: ReactNode
  toolbar?: ReactNode
  footer?: ReactNode
  children: ReactNode
}

/** The shell owns outer padding; this component owns page slots and scroll mode. */
export function PageLayout({ mode = 'document', width = 'full', header, overview, toolbar, footer, children }: PageLayoutProps) {
  return <div className={cn('page-layout', width === 'reading' && 'max-w-3xl')} data-mode={mode}>
    <div className="page-layout-frame">
      {header && <div className="page-layout-slot">{header}</div>}
      {overview && <div className="page-layout-slot">{overview}</div>}
      {toolbar && <div className="page-layout-slot">{toolbar}</div>}
      <div className="page-layout-body">{children}</div>
      {footer && <div className="page-layout-slot">{footer}</div>}
    </div>
  </div>
}

interface PageHeaderProps {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  level?: 1 | 2
  id?: string
  titleRef?: Ref<HTMLHeadingElement>
}

export function PageHeader({ title, description, actions, level = 1, id, titleRef }: PageHeaderProps) {
  const Heading = level === 1 ? 'h1' : 'h2'
  return <header className="flex min-w-0 flex-wrap items-start justify-between gap-3">
    <div className="min-w-0">
      <Heading id={id} ref={titleRef} tabIndex={titleRef ? -1 : undefined}
        className={cn('scroll-mt-4 break-words font-semibold focus-visible:outline-2 focus-visible:outline-ring', level === 1 ? 'text-page' : 'text-section')}>{title}</Heading>
      {description && <p className="mt-1 text-caption text-muted-foreground">{description}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </header>
}

interface WorkspacePanel {
  label: string
  scrollLabel?: string
  content: ReactNode
  surface?: 'plain' | 'card'
}
interface SplitWorkspaceProps {
  primary: WorkspacePanel
  secondary: WorkspacePanel
  activePanel: 'primary' | 'secondary'
  onActivePanelChange: (panel: 'primary' | 'secondary') => void
}

export function SplitWorkspace({ primary, secondary, activePanel, onActivePanelChange }: SplitWorkspaceProps) {
  return <div className="split-workspace">
    <div className="workspace-tabs">
      <SegmentTabs tabs={[{ value: 'primary', label: primary.label }, { value: 'secondary', label: secondary.label }]}
        value={activePanel} onChange={value => onActivePanelChange(value === 'secondary' ? 'secondary' : 'primary')} />
    </div>
    <div className="workspace-columns">
      {([{ key: 'primary', panel: primary }, { key: 'secondary', panel: secondary }] as const).map(({ key, panel }) => (
        <section key={key} aria-label={panel.scrollLabel ?? panel.label} tabIndex={0}
          data-active={activePanel === key} data-surface={panel.surface ?? 'plain'}
          className="workspace-panel focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2">
          {panel.content}
        </section>
      ))}
    </div>
  </div>
}
