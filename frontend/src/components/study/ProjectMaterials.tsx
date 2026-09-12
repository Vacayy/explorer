import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import api from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { errorMessage } from './useStudy'
export function ProjectMaterials({pid,open,onOpenChange,onAdded}:{pid:number;open:boolean;onOpenChange:(v:boolean)=>void;onAdded:(ids:number[])=>void}){
 const [query,setQuery]=useState(''),[picked,setPicked]=useState<number[]>([]),[busy,setBusy]=useState(false),[mode,setMode]=useState('search')
 const [title,setTitle]=useState(''),[url,setUrl]=useState(''),[text,setText]=useState('')
 const q=useQuery({queryKey:['study-material-search',query],queryFn:async()=>(await api.get<{id:number;title:string;source_type:string;published_at:string;url:string}[]>('/api/spine/study-projects/search',{params:{q:query}})).data,enabled:open,staleTime:30000})
 async function add(){setBusy(true);try{const {data}=mode==='search'?await api.post(`/api/spine/study-projects/${pid}/documents`,{document_ids:picked}):await api.post(`/api/spine/study-projects/${pid}/clips`,{title,url,text});onAdded(data.study_ids);setPicked([]);setTitle('');setUrl('');setText('');onOpenChange(false)}catch(e){toast.error(errorMessage(e))}finally{setBusy(false)}}
 return <Dialog open={open} onOpenChange={v=>!busy&&onOpenChange(v)}><DialogContent className="sm:max-w-2xl max-h-[85dvh] overflow-auto"><DialogHeader><DialogTitle>함께 공부할 자료 추가</DialogTitle><DialogDescription>수집된 자료를 여러 개 고르거나, 직접 읽을 글을 붙여넣으세요.</DialogDescription></DialogHeader><SegmentTabs tabs={[{value:'search',label:'수집 자료 찾기'},{value:'paste',label:'본문 붙여넣기'}]} value={mode} onChange={setMode}/>
 {mode==='search'?<><Input autoFocus aria-label="수집 자료 검색" value={query} onChange={e=>setQuery(e.target.value)} placeholder="제목 또는 수집된 자료의 URL 검색"/><p className="text-caption text-muted-foreground">최신 50건 표시 · 검색해서 범위를 좁힐 수 있습니다.</p><div className="max-h-80 overflow-auto space-y-1">{q.isLoading?<p>검색 중…</p>:q.isError?<Button onClick={()=>q.refetch()}>다시 검색</Button>:q.data?.length?q.data.map(d=><label key={d.id} className="flex items-start gap-3 rounded-xl p-3 hover:bg-muted cursor-pointer"><Checkbox aria-label={`자료 선택 ${d.id}`} checked={picked.includes(d.id)} onCheckedChange={v=>setPicked(p=>v?[...p,d.id]:p.filter(id=>id!==d.id))}/><span className="min-w-0"><span className="block text-sm">{d.title||'제목 없는 자료'}</span><span className="text-caption text-muted-foreground">{d.source_type} · {d.published_at?.slice(0,10)||'발행일 미상'}</span></span></label>):<p className="text-sm text-muted-foreground p-4">수집된 자료가 없습니다. 미수집 링크는 본문 붙여넣기로 추가할 수 있습니다.</p>}</div></>:<div className="space-y-3"><Input aria-label="자료 제목" placeholder="자료 제목" value={title} maxLength={160} onChange={e=>setTitle(e.target.value)}/><Input aria-label="자료 출처 URL" placeholder="출처 URL (선택, 자동 수집하지 않음)" value={url} maxLength={2000} onChange={e=>setUrl(e.target.value)}/><Textarea className="min-h-48" aria-label="자료 본문" placeholder="읽을 원문이나 나의 메모를 붙여넣으세요." value={text} maxLength={1000000} onChange={e=>setText(e.target.value)}/></div>}
 <Button disabled={busy||(mode==='search'?picked.length===0||picked.length>30:!title.trim()||!text.trim())} onClick={add}>{busy?'추가 중…':mode==='search'?`선택한 ${picked.length}개 자료 추가`:'프로젝트에 추가'}</Button></DialogContent></Dialog>
}
