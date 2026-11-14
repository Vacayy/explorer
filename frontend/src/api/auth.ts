import api, { API_BASE } from '@/api/client'
import type { LogoutReply, MemberSession } from '@/types'

/** Do not persist this response or its CSRF token in browser storage. */
export async function getMemberSession(signal?: AbortSignal): Promise<MemberSession> {
  const { data } = await api.get<MemberSession>('/api/auth/session', { signal, withCredentials: true })
  return data
}

export async function logoutMember(csrfToken: string): Promise<LogoutReply> {
  const { data } = await api.post<LogoutReply>('/api/auth/logout', null, {
    headers: { 'X-CSRF-Token': csrfToken }, withCredentials: true,
  })
  return data
}

/** A browser navigation, not a JSON fetch; callback is handled by the backend. */
export function googleLoginUrl(returnTo = '/'): string {
  const url = new URL('/api/auth/google/start', new URL(API_BASE, window.location.origin))
  url.searchParams.set('return_to', returnTo)
  return url.toString()
}
