import { useId } from 'react'
import { ComponentNode, ComponentRegistry, useA2UIComponent } from '@a2ui/react'
import type { A2UIComponentProps, Types } from '@a2ui/react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

/** A2UI 0.11's stock MultipleChoice ignores its bound value. Use the same
 * processor/action model with our accessible controls so restored answers match
 * what is displayed, including defaults that are not the first option. */
function AnalysisChoice({ node, surfaceId }: A2UIComponentProps<Types.MultipleChoiceNode>) {
  const id = useId()
  const { resolveString, getValue, setValue } = useA2UIComponent(node, surfaceId)
  const props = node.properties
  const path = props.selections?.path
  const selected = path ? getValue(path) : null
  const value = Array.isArray(selected) ? String(selected[0] ?? '') : typeof selected === 'string' ? selected : ''
  // Standard v0.8 MultipleChoice has no label field. The server provides label
  // text in its data model, which also survives protocol schema validation.
  const label = path ? getValue(`${path}_label`) : null
  return <div className="space-y-2 py-1">
    <Label htmlFor={id}>{typeof label === 'string' ? label : '분석 조건'}</Label>
    <Select value={value} onValueChange={next => { if (path) setValue(path, [next]) }}>
      <SelectTrigger id={id} className="bg-card"><SelectValue placeholder="조건 선택" /></SelectTrigger>
      <SelectContent>{(props.options ?? []).map(option => <SelectItem key={option.value} value={option.value}>{resolveString(option.label) ?? option.value}</SelectItem>)}</SelectContent>
    </Select>
  </div>
}

function AnalysisAction({ node, surfaceId }: A2UIComponentProps<Types.ButtonNode>) {
  const { sendAction } = useA2UIComponent(node, surfaceId)
  return <Button type="button" className="mt-3" onClick={() => { if (node.properties.action) sendAction(node.properties.action) }}>
    <ComponentNode node={node.properties.child} surfaceId={surfaceId} />
  </Button>
}

// Run inside the mounted provider: its first render initializes the defaults.
export function registerAnalysisCatalog() {
  const registry = ComponentRegistry.getInstance()
  registry.register('MultipleChoice', { component: AnalysisChoice })
  registry.register('Button', { component: AnalysisAction })
}
