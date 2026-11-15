import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import { apiQuery, toApiError } from '@/api/query'
import { useMemberAccess } from '@/components/auth/MemberAccess'
import type { PortfolioPrinciple, MemberPrincipleInput, MemberPrincipleRuleOption, MemberPrincipleState } from '@/types'
const BASE = '/api/member/portfolio/principles'
function useScope() {
  const access = useMemberAccess()
  return { access, key: ['member', access.session?.user?.id, 'portfolio', 'principles'], enabled: access.status === 'member' || access.status === 'operator' }
}
export function useMemberPrinciples() {
  const { key, enabled } = useScope()
  return useQuery({ ...apiQuery<PortfolioPrinciple[]>({ key, url: BASE, enabled }), retry: false, gcTime: 0 })
}
export function useMemberPrincipleState() {
  const { key, enabled } = useScope()
  return useQuery({ ...apiQuery<MemberPrincipleState>({ key: [...key, 'state'], url: `${BASE}/state`, enabled }), retry: false, gcTime: 0 })
}
export function useMemberPrincipleOptions() {
  const { key, enabled } = useScope()
  return useQuery({ ...apiQuery<MemberPrincipleRuleOption[]>({ key: [...key, 'rules'], url: `${BASE}/rules`, enabled }), retry: false, gcTime: 0 })
}
export function useSaveMemberPrinciple() {
  const { access, enabled, key } = useScope(); const client = useQueryClient()
  return useMutation({ mutationFn: async ({ id, body }: { id?: number; body: MemberPrincipleInput }) => {
    if (!enabled || !access.session?.csrf_token) throw new Error('로그인을 확인해 주세요.')
    const config = { withCredentials: true, headers: { 'X-CSRF-Token': access.session.csrf_token } }
    try { return id == null ? (await api.post<{ id: number; ok: boolean }>(BASE, body, config)).data
      : (await api.put<{ ok: boolean }>(`${BASE}/${id}`, body, config)).data }
    catch (error) { throw toApiError(error) }
  }, onSuccess: () => client.invalidateQueries({ queryKey: key }) })
}
export function useDeleteMemberPrinciple() {
  const { access, enabled, key } = useScope(); const client = useQueryClient()
  return useMutation({ mutationFn: async (id: number) => {
    if (!enabled || !access.session?.csrf_token) throw new Error('로그인을 확인해 주세요.')
    try { return (await api.delete<{ ok: boolean }>(`${BASE}/${id}`, { withCredentials: true, headers: { 'X-CSRF-Token': access.session.csrf_token } })).data }
    catch (error) { throw toApiError(error) }
  }, onSuccess: () => client.invalidateQueries({ queryKey: key }) })
}
