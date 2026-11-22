import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'
import { UserRound } from 'lucide-react'
import { getMemberSession, googleLoginUrl, logoutMember } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { PageContainer } from '@/components/shared/PageContainer'
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

/** 운영자 전용·회원 전용 API를 불러도 되는가 — 공개 모드의 비로그인 방문자는 둘 다 아니다. 부르면 401이 '일부 데이터를
 * 불러오지 못했습니다'로 보인다(2026-11-22). 공급자가 없으면(비공개 모드·단독 렌더) 예전처럼 둘 다 허용한다. */
export function useAccessScope() {
  const status = useContext(AccessContext)?.status ?? 'private'
  return { operator: status === 'private' || status === 'operator',
           member: status === 'private' || status === 'member' || status === 'operator' }
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
  return <DropdownMenu>
    <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="rounded-full" aria-label="계정 메뉴"><UserRound aria-hidden /></Button></DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      {access.status === 'loading' && <DropdownMenuItem disabled>계정 확인 중</DropdownMenuItem>}
      {access.status === 'error' && <DropdownMenuItem onSelect={access.retry}>로그인 확인 재시도</DropdownMenuItem>}
      {access.status === 'anonymous' && (access.session?.login_available === false
        ? <DropdownMenuItem disabled>로그인 준비 중</DropdownMenuItem>
        : <DropdownMenuItem asChild><a href={googleLoginUrl(location.pathname + location.search)}>Google 로그인</a></DropdownMenuItem>)}
      {(access.status === 'member' || access.status === 'operator') && <>
        <DropdownMenuItem asChild><Link to="/account">마이페이지</Link></DropdownMenuItem>
        <DropdownMenuItem disabled={access.busy} onSelect={() => { void access.logout() }}>로그아웃</DropdownMenuItem>
      </>}
      {access.logoutError && <DropdownMenuItem disabled>로그아웃 실패. 다시 시도해 주세요.</DropdownMenuItem>}
    </DropdownMenuContent>
  </DropdownMenu>
}

export function AccountPage() {
  const access = useMemberAccess()
  return <PageContainer><h1 className="text-xl font-medium">마이페이지</h1>
    {access.status === 'loading' && <p role="status">계정 확인 중</p>}
    {access.status === 'error' && <Button onClick={access.retry}>계정 확인 재시도</Button>}
    {access.status === 'anonymous' && <Button asChild><a href={googleLoginUrl('/account')}>Google 로그인</a></Button>}
    {(access.status === 'member' || access.status === 'operator') && <p>{access.status === 'operator' ? '운영자 계정' : '회원 계정'}으로 로그인했습니다.</p>}
  </PageContainer>
}
