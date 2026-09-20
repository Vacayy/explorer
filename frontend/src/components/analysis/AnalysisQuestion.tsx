import { Component, useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { A2UIProvider, A2UIRenderer, useA2UI } from '@a2ui/react'
import type { A2UIClientEventMessage, ServerToClientMessage } from '@a2ui/react'
import '@a2ui/react/styles'
import { registerAnalysisCatalog } from './a2uiCatalog'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { AnalysisPending } from './types'

class SurfaceBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    return this.state.failed ? <p role="alert" className="text-sm text-destructive">조건 확인 화면을 표시하지 못했습니다. 실행을 취소한 뒤 다시 질문해 주세요.</p> : this.props.children
  }
}

function SurfaceMessages({ messages, onError }: { messages: ServerToClientMessage[]; onError: (message: string) => void }) {
  const { processMessages, clearSurfaces } = useA2UI()
  // Polling returns new objects; loading a surface again would erase typed answers.
  const initialMessages = useRef(messages)
  useEffect(() => {
    try { registerAnalysisCatalog(); clearSurfaces(); processMessages(initialMessages.current) }
    catch { onError('조건 확인 화면을 불러오지 못했습니다. 실행을 취소한 뒤 다시 질문해 주세요.') }
  }, [processMessages, clearSurfaces, onError])
  return null
}

export function AnalysisQuestion({ pending, busy, onAnswer }: {
  pending: AnalysisPending
  busy: boolean
  onAnswer: (payload: Record<string, unknown>) => Promise<unknown>
}) {
  const [error, setError] = useState('')
  const sending = useRef(false)
  const handleError = useCallback((message: string) => setError(message), [])
  async function handleAction(message: A2UIClientEventMessage) {
    if (busy || sending.current) return
    const action = (message as { userAction?: Record<string, unknown> }).userAction
    if (!action) return
    sending.current = true
    try { await onAnswer(action) }
    catch { /* The parent shows the API error and preserves this form. */ }
    finally { sending.current = false }
  }
  return <Card className="bg-hypothesis/5">
    <CardHeader><CardTitle className="text-card-title">분석 조건 확인</CardTitle><p className="text-sm text-muted-foreground">{pending.question}</p></CardHeader>
    <CardContent>
      <SurfaceBoundary>
        <A2UIProvider onAction={handleAction}>
          <SurfaceMessages messages={pending.a2ui} onError={handleError} />
          <fieldset disabled={busy} aria-busy={busy} className="min-w-0 space-y-3 disabled:opacity-60">
            <legend className="sr-only">분석에 적용할 조건</legend>
            {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : <A2UIRenderer surfaceId={pending.surfaceId} className="analysis-surface text-sm" fallback={<p role="status" className="text-muted-foreground">조건을 불러오는 중…</p>} />}
          </fieldset>
        </A2UIProvider>
      </SurfaceBoundary>
      {busy && <p role="status" className="mt-3 text-caption text-muted-foreground">응답을 보내는 중…</p>}
    </CardContent>
  </Card>
}
