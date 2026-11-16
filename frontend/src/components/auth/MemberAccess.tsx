import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { getMemberSession, googleLoginUrl, logoutMember } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { PUBLIC_ACCESS } from '@/lib/accessMode'
import { clearMemberBrowserState, leaveMemberSession } from '@/lib/memberReset'
import type { MemberSession } from '@/types'

export const MEMBER_SESSION_KEY = ['auth', 'member-session'] as const
type Access = {
  status: 'private' | 'loading' | 'anonymous' | 'member' | 'operator' | 'error'
  session: MemberSession | undefined
  retry: () => void
  logout: () => Promise<void>
  busy: boolean
  logoutError: boolean
}
const AccessContext = createContext<Access | null>(null)

export function MemberAccessProvider({ children, enabled = PUBLIC_ACCESS }: { children: ReactNode; enabled?: boolean }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: MEMBER_SESSION_KEY, queryFn: ({ signal }) => getMemberSession(signal),
    enabled, retry: false, staleTime: 0, refetchOnWindowFocus: true })
  const [busy, setBusy] = useState(false)
  const [logoutError, setLogoutError] = useState(false)
  const previous = useRef<string | undefined>(undefined)
  const transition = useRef(false)
  const session = query.data
  const valid = session && (session.authenticated
    ? !!session.user && !!session.csrf_token
    : session.user === null && session.csrf_token === null)
  const status: Access['status'] = !enabled ? 'private' : busy || query.isPending ? 'loading'
    : query.isError || !valid ? 'error' : session?.authenticated ? session.user!.role : 'anonymous'

  async function resetAndLeave() {
    transition.current = true
    setBusy(true)
    await client.cancelQueries()
    clearMemberBrowserState()
    client.clear()
    leaveMemberSession()
  }

  useEffect(() => {
    if (!enabled || !query.isSuccess || !valid || transition.current) return
    const current = session?.user ? `${session.user.id}:${session.user.role}` : 'anonymous'
    if (previous.current !== undefined && previous.current !== current) {
      void resetAndLeave()
    } else {
      previous.current = current
    }
    // Only a confirmed identity change clears state; a transient failure does not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, query.isSuccess, valid, session?.user?.id, session?.user?.role])

  async function logout() {
    if (busy || !session?.authenticated || !session.csrf_token) return
    setBusy(true); setLogoutError(false)
    try {
      const reply = await logoutMember(session.csrf_token)
      if (!reply.ok) throw new Error('Logout rejected')
      await resetAndLeave()
    } catch {
      setBusy(false); setLogoutError(true)
    }
  }
  return <AccessContext.Provider value={{ status, session, busy, logoutError, logout, retry: () => { void query.refetch() } }}>
    {children}
  </AccessContext.Provider>
}

export function useMemberAccess() {
  const access = useContext(AccessContext)
  if (!access) throw new Error('MemberAccessProvider is required')
  return access
}

export function AccountControl() {
  const access = useMemberAccess()
  const location = useLocation()
  if (access.status === 'private') return null
  if (access.status === 'loading') return <span role="status" className="text-xs text-ink-3">계정 확인 중</span>
  if (access.status === 'error') return <Button variant="outline" size="sm" onClick={access.retry}>로그인 확인 재시도</Button>
  if (access.session?.login_available === false) return <span role="status" className="text-xs text-ink-3">로그인 준비 중</span>
  if (access.status === 'anonymous') return <Button asChild size="sm" variant="outline">
    <a href={googleLoginUrl(location.pathname + location.search)}>Google 로그인</a>
  </Button>
  return <div className="flex items-center gap-2">
    <span className="text-xs text-ink-2">{access.status === 'operator' ? '운영자' : '로그인됨'}</span>
    <Button size="sm" variant="ghost" disabled={access.busy} onClick={() => { void access.logout() }}>로그아웃</Button>
    {access.logoutError && <span role="alert" className="text-xs text-destructive">로그아웃하지 못했습니다. 다시 시도해 주세요.</span>}
  </div>
}
