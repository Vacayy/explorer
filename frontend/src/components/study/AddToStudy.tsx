import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FolderPlus } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { useProjects } from './useProjects'
import { errorMessage } from './useStudy'
export function AddToStudy({documentId}:{documentId:number}){
 const [open,setOpen]=useState(false),[title,setTitle]=useState(''),[busy,setBusy]=useState(false)
 const cache=useQueryClient()
 return <><Button size="sm" variant="ghost" onClick={()=>setOpen(true)}><FolderPlus aria-hidden="true"/>스터디에 추가</Button><Dialog open={open} onOpenChange={v=>!busy&&setOpen(v)}><DialogContent><DialogHeader><DialogTitle>함께 공부할 프로젝트</DialogTitle><DialogDescription>자료만 추가하고 지금 읽던 화면에 머무릅니다.</DialogDescription></DialogHeader><ProjectPicker busy={busy} onPick={async pid=>{setBusy(true);try{await api.post(`/api/spine/study-projects/${pid}/documents`,{document_ids:[documentId]});await cache.invalidateQueries({queryKey:['spine','study-projects']});await cache.invalidateQueries({queryKey:['spine','study-project',pid]});setOpen(false);toast.success('스터디에 추가했습니다.')}catch(e){toast.error(errorMessage(e))}finally{setBusy(false)}}}/><form className="flex gap-2 border-t pt-4" onSubmit={async e=>{e.preventDefault();setBusy(true);try{const {data}=await api.post('/api/spine/study-projects',{title:title.trim()||'새 스터디'});await api.post(`/api/spine/study-projects/${data.id}/documents`,{document_ids:[documentId]});await cache.invalidateQueries({queryKey:['spine','study-projects']});setOpen(false);setTitle('');toast.success('새 스터디에 추가했습니다.')}catch(e){toast.error(errorMessage(e))}finally{setBusy(false)}}}><Input aria-label="새 스터디 이름" placeholder="새 스터디 이름 (나중에 변경 가능)" value={title} maxLength={160} onChange={e=>setTitle(e.target.value)}/><Button disabled={busy} type="submit">새로 만들고 추가</Button></form></DialogContent></Dialog></>
}
function ProjectPicker({busy,onPick}:{busy:boolean;onPick:(id:number)=>void}){const q=useProjects();return <div className="max-h-64 overflow-auto space-y-1">{q.isLoading?<p className="text-sm">불러오는 중…</p>:q.isError?<Button onClick={()=>q.refetch()}>다시 불러오기</Button>:q.data?.length?q.data.map(p=><Button key={p.id} className="w-full justify-between" variant="ghost" disabled={busy} onClick={()=>onPick(p.id)}><span className="truncate">{p.title}</span><span className="text-muted-foreground">{p.document_count}개 자료</span></Button>):<p className="text-sm text-muted-foreground">새 프로젝트를 만들어 시작하세요.</p>}</div>}
