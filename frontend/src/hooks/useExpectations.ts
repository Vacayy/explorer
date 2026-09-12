import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getJson, postJson } from '@/api/query'
import type { ExpectationPage, ExpectationDocument, ExpectationJob, ExpectationStatement, ExpectationComparison, ExpectationHistory } from '@/types'

export const EXP_API = '/api/experiments/expectations'
export const expKey = ['expectation-experiment'] as const
export function useExpectationDocuments(product: string, before: number | undefined) {
  return useQuery({ queryKey: [...expKey, 'documents', product, before],
    queryFn: () => getJson<ExpectationPage>(`${EXP_API}/documents`, { product: product || undefined, before_id: before, limit: 20 }) })
}
export function useExpectationDocument(id: number) {
  return useQuery({ queryKey: [...expKey, 'document', id], queryFn: () => getJson<ExpectationDocument>(`${EXP_API}/documents/${id}`), enabled: id > 0 })
}
export function useExpectationStatements(docId?: number) {
  return useQuery({ queryKey: [...expKey, 'statements', docId], queryFn: () => getJson<ExpectationStatement[]>(`${EXP_API}/statements`, { doc_id: docId }) })
}
export function useExpectationJobs(docId: number) {
  const qc = useQueryClient()
  const jobs = useQuery({ queryKey: [...expKey, 'jobs', docId], queryFn: () => getJson<ExpectationJob[]>(`${EXP_API}/jobs`, { doc_id: docId }), enabled: docId > 0,
    refetchInterval: q => q.state.data?.some(j => j.state === 'queued' || j.state === 'running') ? 1200 : false })
  useEffect(() => {
    if (jobs.data?.some(j => j.state === 'done')) void qc.invalidateQueries({ queryKey: [...expKey, 'statements'] })
  }, [jobs.data, qc])
  return jobs
}
export function useExpectationWrite<T = unknown>(url: string) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (body: unknown) => postJson<T>(`${EXP_API}${url}`, body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: expKey }) } })
}
export function useExpectationComparison(id: number) {
  return useQuery({ queryKey: [...expKey, 'comparison', id], queryFn: () => getJson<ExpectationComparison>(`${EXP_API}/statements/${id}/comparison`), enabled: id > 0 })
}
export function useExpectationHistory(id: number) {
  return useQuery({ queryKey: [...expKey, 'history', id], queryFn: () => getJson<ExpectationHistory>(`${EXP_API}/statements/${id}/history`), enabled: id > 0 })
}

export function useStatementEvidence(id: number, enabled: boolean) {
  return useQuery({ queryKey: [...expKey, 'snapshot', id], queryFn: () => getJson<ExpectationDocument>(`${EXP_API}/statements/${id}/evidence`), enabled })
}
