import type { StudyResearch } from './ResearchResults'
import { useQuery } from '@tanstack/react-query'
import api from '@/api/client'
import type { Annotation } from './useStudy'
export interface ProjectDocument {id:number;document_id:number|null;title:string;source_type:string;source_url:string;published_at:string|null;body_length:number;annotation_count:number}
export interface ProjectTurn {id:number;message_id:number;question:string;status:string;error:string|null;created_at:string;context:{scope:string;research?:StudyResearch;sources:{study_id:number;title:string;scope:string;annotations:Annotation[]}[]}}
export interface StudyProject {id:number;title:string;note:string;revision:number;conversation_id:number|null;updated_at:string;document_count?:number;documents:ProjectDocument[];turns:ProjectTurn[]}
export const projectKey=(id:number)=>['spine','study-project',id]
export function useProjects(){return useQuery({queryKey:['spine','study-projects'],queryFn:async()=>(await api.get<StudyProject[]>('/api/spine/study-projects')).data})}
export function useProject(id:number){return useQuery({queryKey:projectKey(id),queryFn:async()=>(await api.get<StudyProject>(`/api/spine/study-projects/${id}`)).data,enabled:Number.isInteger(id)&&id>0,refetchInterval:q=>q.state.data?.turns.some(t=>t.status==='pending')?1500:false})}
