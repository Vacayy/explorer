import { PauseCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatRelativeTime } from '@/utils/format'

/** 판정 엔진(관리자 '질문 트래커 갱신')이 꺼져 논지·관심 이유 판정과 알림이 멈췄음을 알린다 — 옛 판정을 오늘 것처럼 보이지 않게. */
export function JudgingPausedNotice({ judgedAt }: { judgedAt: string | null }) {
  // DB 시각은 UTC 'YYYY-MM-DD HH:MM:SS'
  const last = judgedAt ? formatRelativeTime(`${judgedAt.replace(' ', 'T')}Z`) : null
  return <div role="status" className="flex gap-2 rounded-lg border p-3 text-sm">
    <PauseCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
    <p>판정이 멈춰 있습니다{last ? ` (마지막 판정 ${last})` : ''}. <Link to="/admin" className="text-primary hover:underline">관리자</Link>에서
      ‘질문 트래커 갱신’이 꺼져 있어 아래 판정과 텔레그램 알림이 갱신되지 않습니다.</p>
  </div>
}
