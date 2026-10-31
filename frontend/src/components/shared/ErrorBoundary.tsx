import { Component, type ErrorInfo, type ReactNode } from 'react'
import { ErrorState } from './ErrorState'

/** Place outside a page/widget component so failures in its render are isolated. Key by route to reset on navigation. */
export class ErrorBoundary extends Component<{ children: ReactNode; onReset?: () => void }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('화면 렌더링 오류', error, info.componentStack)
  }
  render() {
    if (this.state.failed) return <ErrorState message="화면을 표시하지 못했습니다. 다시 시도해 주세요." onRetry={() => {
      this.props.onReset?.()
      this.setState({ failed: false })
    }} />
    return this.props.children
  }
}
