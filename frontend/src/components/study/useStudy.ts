import { toApiError } from '@/api/errors'
import type { StudyResearch } from '@/components/study/ResearchResults'
import type { StudyIntent } from '@/types'
import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
export interface Annotation { id:number; kind:'highlight'|'comment'; intent?:'highlight'|StudyIntent; start_offset:number; end_offset:number; exact:string; comment:string; revision:number }
export interface StudyTurn { created_at:string; id:number; message_id:number; status:string; error:string|null; question:string; context:{scope:string; annotations:Annotation[];research?:StudyResearch} }
export interface Study { id:number; document_id:number|null; project_id:number; title:string; source_url:string; source_type:string; body_kind:string; body:string; content_hash:string; conversation_id:number|null; annotations:Annotation[]; turns:StudyTurn[] }
export const studyKey=(id:number)=>['spine','study',id]
export function useStudy(id:number){return useQuery({queryKey:studyKey(id),queryFn:async()=>(await api.get<Study>(`/api/spine/studies/${id}`)).data,enabled:Number.isInteger(id)&&id>0,refetchInterval:q=>q.state.data?.turns.some(t=>t.status==='pending')?1500:false})}
export function errorMessage(error: unknown) { return toApiError(error).message }
