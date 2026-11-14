import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import { apiQuery, toApiError } from '@/api/query'
import { useMemberAccess } from '@/components/auth/MemberAccess'
import type { PortfolioSummary, PortfolioHistoryPoint, PortfolioTransaction, PortfolioTxInput, PortfolioCompany } from '@/types'

const BASE = '/api/member/portfolio'

function useScope() {
  const access = useMemberAccess()
  const enabled = access.status === 'member' || access.status === 'operator'
  return { access, enabled, key: ['member', access.session?.user?.id, 'portfolio'] as const }
}
export function useMemberPortfolio() {
  const { enabled, key } = useScope()
  return useQuery({ ...apiQuery<PortfolioSummary>({ key: [...key, 'summary'], url: BASE, enabled }), retry: false, gcTime: 0 })
}
export function useMemberPortfolioHistory() {
  const { enabled, key } = useScope()
  return useQuery({ ...apiQuery<PortfolioHistoryPoint[]>({ key: [...key, 'history'], url: `${BASE}/history`, enabled }), retry: false, gcTime: 0 })
}
export function useMemberPortfolioTransactions() {
  const { enabled, key } = useScope()
  return useQuery({ ...apiQuery<PortfolioTransaction[]>({ key: [...key, 'transactions'], url: `${BASE}/transactions`, enabled }), retry: false, gcTime: 0 })
}
export function useMemberPortfolioCompanies(query: string) {
  const { enabled, key } = useScope()
  const q = query.trim()
  return useQuery({ ...apiQuery<PortfolioCompany[]>({ key: [...key, 'companies', q], url: `${BASE}/companies`, params: { q }, enabled: enabled && q.length > 0 }), retry: false, gcTime: 0 })
}
export function useAddMemberPortfolioTransaction() {
  const { access, enabled, key } = useScope()
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: PortfolioTxInput) => {
      if (!enabled || !access.session?.csrf_token) throw new Error('로그인을 확인해 주세요.')
      try {
        return (await api.post<{ ok: boolean; id: number }>(`${BASE}/transactions`, body, {
          withCredentials: true, headers: { 'X-CSRF-Token': access.session.csrf_token },
        })).data
      } catch (e) { throw toApiError(e) }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  })
}
export function useDeleteMemberPortfolioTransaction() {
  const { access, enabled, key } = useScope()
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      if (!enabled || !access.session?.csrf_token) throw new Error('로그인을 확인해 주세요.')
      try {
        return (await api.delete<{ ok: boolean }>(`${BASE}/transactions/${id}`, {
          withCredentials: true, headers: { 'X-CSRF-Token': access.session.csrf_token },
        })).data
      } catch (e) { throw toApiError(e) }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  })
}
