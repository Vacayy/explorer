import type { StudyResearch } from '@/components/study/ResearchResults'
import type { StudyIntent } from '@/types'
import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
export interface Annotation { id:number; kind:'highlight'|'comment'; intent?:'highlight'|StudyIntent; start_offset:number; end_offset:number; exact:string; comment:string; revision:number }
export interface StudyTurn { created_at:string; id:number; message_id:number; status:string; error:string|null; question:string; context:{scope:string; annotations:Annotation[];research?:StudyResearch} }
export interface Study { id:number; document_id:number|null; project_id:number; title:string; source_url:string; source_type:string; body_kind:string; body:string; content_hash:string; conversation_id:number|null; annotations:Annotation[]; turns:StudyTurn[] }
export const studyKey=(id:number)=>['spine','study',id]
export function useStudy(id:number){return useQuery({queryKey:studyKey(id),queryFn:async()=>(await api.get<Study>(`/api/spine/studies/${id}`)).data,enabled:Number.isInteger(id)&&id>0,refetchInterval:q=>q.state.data?.turns.some(t=>t.status==='pending')?1500:false})}
export function errorMessage(error:unknown){const detail=(error as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;if(typeof detail==='string')return detail;if(Array.isArray(detail))return detail.map(d=>typeof d?.msg==='string'?d.msg:'입력값을 확인해 주세요.').join(' ');return '요청을 완료하지 못했습니다. 다시 시도해 주세요.'}
