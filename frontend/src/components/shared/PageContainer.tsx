import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'

/**
 * 레거시 페이지 호환 컨테이너 — 신규 조합은 PageLayout 사용 (docs/DESIGN_SYSTEM.md).
 *
 * - width="full"    : 셸 폭 전부 사용 (데이터 밀집 화면 기본값)
 * - width="reading" : max-w-3xl — 읽기 중심 문서 화면 (doc/source/archive)
 * - gap="md"        : space-y-6 (기본) / gap="sm" : space-y-4 (밀집 화면)
 *
 * 규칙: 페이지는 자체 max-w/padding을 지정하지 않는다 — 폭은 셸(--layout-shell)과
 * 이 컨테이너만이 결정한다. 풀하이트 앱형 페이지(예: ChatPage)만 예외로
 * h-[calc(100dvh-var(--shell-offset))] 패턴을 쓴다.
 */
interface PageContainerProps {
  width?: 'full' | 'reading'
  gap?: 'sm' | 'md'
  className?: string
  children: ReactNode
}

const WIDTHS = { full: '', reading: 'max-w-3xl' } as const
const GAPS = { sm: 'space-y-4', md: 'space-y-6' } as const

export function PageContainer({ width = 'full', gap = 'md', className, children }: PageContainerProps) {
  return (
    <div className={cn('w-full min-w-0', WIDTHS[width], GAPS[gap], className)}>
      {children}
    </div>
  )
}
