import { useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/api/client'
import type { StudyAction, StudyActionRequest } from '@/types'

export const studyActionsKey = (id: number) => ['spine', 'study-actions', id]

export function useStudyActions(id: number) {
  const cache = useQueryClient()
  const requests = useRef(new Map<string, { key: string; pending?: Promise<StudyAction> }>())
  const query = useQuery({
    queryKey: studyActionsKey(id),
    queryFn: async () => (await api.get<StudyAction[]>(`/api/spine/studies/${id}/actions`)).data,
    enabled: Number.isInteger(id) && id > 0,
    refetchInterval: q => q.state.data?.some(a => a.status === 'queued' || a.status === 'running') ? 1500 : false,
  })
  async function refresh() {
    await Promise.all([
      cache.invalidateQueries({ queryKey: ['spine', 'study-actions'] }),
      cache.invalidateQueries({ queryKey: ['spine', 'study', id] }),
      cache.invalidateQueries({ queryKey: ['spine', 'studies'] }),
      cache.invalidateQueries({ queryKey: ['spine', 'study-project'] }),
    ])
  }
  function submit(body: StudyActionRequest): Promise<StudyAction> {
    const signature = JSON.stringify(body)
    const old = requests.current.get(signature)
    if (old?.pending) return old.pending
    const entry = old ?? { key: crypto.randomUUID() }
    const pending = api.post<StudyAction>(`/api/spine/studies/${id}/actions`, { ...body, request_key: entry.key })
      .then(async ({ data }) => {
        requests.current.delete(signature)
        cache.setQueryData<StudyAction[]>(studyActionsKey(id), previous =>
          previous?.some(a => a.id === data.id) ? previous : [...(previous ?? []), data])
        await refresh()
        return data
      }).catch(error => {
        // Reuse the key after a lost response; the server returns the same saved mark.
        entry.pending = undefined
        throw error
      })
    entry.pending = pending
    requests.current.set(signature, entry)
    return pending
  }
  async function command(actionId: number | null, name: 'cancel' | 'recover' | 'resume') {
    await api.post(`/api/spine/studies/${id}/actions/${actionId === null ? '' : `${actionId}/`}${name}`)
    await refresh()
  }
  return { ...query, submit, command }
}

export type StudyActionsController = ReturnType<typeof useStudyActions>
