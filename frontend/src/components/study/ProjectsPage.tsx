import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Plus, BookOpen } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { useProjects } from './useProjects'
import { errorMessage } from './useStudy'
import { StudyList } from './StudyList'
export default function ProjectsPage(){
 const q=useProjects(),cache=useQueryClient(),navigate=useNavigate()
 const [title,setTitle]=useState(''),[busy,setBusy]=useState(false)
 return <PageLayout header={<PageHeader title="스터디" description="함께 읽을 자료를 묶고, 내 질문을 이어가는 공간"/>}>
 <form className="flex max-w-xl gap-2 mb-6" onSubmit={async e=>{e.preventDefault();setBusy(true);try{const {data}=await api.post('/api/spine/study-projects',{title:title.trim()||'새 스터디'});await cache.invalidateQueries({queryKey:['spine','study-projects']});navigate(`/study/projects/${data.id}`)}catch(e){toast.error(errorMessage(e))}finally{setBusy(false)}}}><Input aria-label="프로젝트 이름" placeholder="무엇을 함께 공부할까요?" value={title} maxLength={160} onChange={e=>setTitle(e.target.value)}/><Button disabled={busy} type="submit"><Plus/>새 스터디</Button></form>
 {q.isLoading?<p>프로젝트 불러오는 중…</p>:q.isError?<Button onClick={()=>q.refetch()}>다시 불러오기</Button>:q.data?.length?<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 mb-8">{q.data.map(p=><Link key={p.id} to={`/study/projects/${p.id}`} className="rounded-2xl focus-visible:outline-ring"><Card className="h-full hover:bg-muted/40"><CardContent className="p-5"><BookOpen className="size-5 text-primary mb-3"/><h2 className="text-base font-semibold mb-2">{p.title}</h2><p className="text-caption text-muted-foreground">자료 {p.document_count}개 · {p.updated_at.slice(0,10)}</p><p className="mt-3 text-sm text-muted-foreground line-clamp-2">{p.note||'자료를 모으고 첫 질문을 남겨보세요.'}</p></CardContent></Card></Link>)}</div>:<Card className="mb-8"><CardContent className="p-8 text-sm text-muted-foreground">피드에서 ‘스터디에 추가’를 누르거나, 새 프로젝트를 열어 여러 자료를 골라 담으세요.</CardContent></Card>}
 <StudyList/>
 </PageLayout>
}
