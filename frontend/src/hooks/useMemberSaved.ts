import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import { apiQuery, toApiError } from '@/api/query'
import { useMemberAccess } from '@/components/auth/MemberAccess'

import type { MemberSavedDocument, MemberSavedResponse } from '@/types'
const BASE = '/api/member/saved'
function useScope() {
  const access = useMemberAccess()
  return { access, key: ['member', access.session?.user?.id, access.status, 'saved-documents'], enabled: access.status === 'member' || access.status === 'operator' }
}
export function useMemberSaved(offset = 0, docId?: number) {
  const { key, enabled } = useScope()
  return useQuery({ ...apiQuery<MemberSavedResponse>({ key: [...key, offset, docId ?? null], url: BASE,
    params: { offset, limit: 20, ...(docId == null ? {} : { doc_id: docId }) }, enabled, staleTime: 0 }),
    retry: false, gcTime: 0, refetchOnMount: 'always', refetchOnWindowFocus: 'always' })
}
function useMemberSavedMutation<T, R>(request: (body: T, config: { withCredentials: boolean; headers: { 'X-CSRF-Token': string } }) => Promise<{ data: R }>) {
  const { access, key, enabled } = useScope()
  const client = useQueryClient()
  return useMutation({ mutationFn: async (body: T) => {
    if (!enabled || !access.session?.csrf_token) throw new Error('로그인을 확인해 주세요.')
    try { return (await request(body, { withCredentials: true, headers: { 'X-CSRF-Token': access.session.csrf_token } })).data }
    catch (error) { throw toApiError(error) }
  }, onSuccess: () => client.invalidateQueries({ queryKey: key }) })
}
export function useSaveMemberDocument() {
  return useMemberSavedMutation((body: { doc_id: number; note?: string | null }, config) => api.post<MemberSavedDocument>(BASE, body, config))
}
export function useUpdateMemberSavedNote() {
  return useMemberSavedMutation(({ id, note }: { id: number; note: string | null }, config) => api.patch<{ ok: boolean }>(`${BASE}/${id}`, { note }, config))
}
export function useDeleteMemberSaved() {
  return useMemberSavedMutation((id: number, config) => api.delete<{ ok: boolean }>(`${BASE}/${id}`, config))
}
