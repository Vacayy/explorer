import { BookOpen, Highlighter, MessageSquarePlus, MousePointer2, ScanSearch, Search } from 'lucide-react'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { StudyIntent, StudyTool } from '@/types'

export const INTENTS: { key: StudyIntent; label: string; Icon: typeof BookOpen }[] = [
  { key: 'explain', label: '이해하기', Icon: BookOpen },
  { key: 'critique', label: '검토하기', Icon: ScanSearch },
  { key: 'related', label: '관련 자료', Icon: Search },
]
export const intentLabel = (intent: string) => INTENTS.find(i => i.key === intent)?.label ?? '강조'
export function StudyPalette({ value, onChange }: { value: StudyTool; onChange: (tool: StudyTool) => void }) {
  const tools = [
    { key: 'read', label: '읽기', Icon: MousePointer2 },
    { key: 'highlight', label: '강조', Icon: Highlighter },
    ...INTENTS,
    { key: 'comment', label: '코멘트', Icon: MessageSquarePlus },
  ] as const
  return <ToggleGroup type="single" value={value} onValueChange={v => { if (v) onChange(v as StudyTool) }} size="sm" className="study-tool-group" aria-label="읽기 도구">
    {tools.map(t => <ToggleGroupItem key={t.key} value={t.key} className="study-tool" data-intent={t.key} aria-label={t.label} title={INTENTS.some(i => i.key === t.key) ? `${t.label} · 드래그하면 AI에 바로 질문` : t.label}>
      <t.Icon aria-hidden="true" />{t.label}
    </ToggleGroupItem>)}
  </ToggleGroup>
}
