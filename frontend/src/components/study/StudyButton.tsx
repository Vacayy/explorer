import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { Button } from '@/components/ui/button'
import { errorMessage } from './useStudy'
export function StudyButton({documentId}:{documentId:number}){
 const [pending,setPending]=useState(false);const navigate=useNavigate()
 async function open(){setPending(true);try{const {data}=await api.post('/api/spine/studies',{document_id:documentId});navigate(`/study/${data.id}`)}catch(e){toast.error(errorMessage(e))}finally{setPending(false)}}
 return <Button size="sm" variant="outline" onClick={open} disabled={pending}><BookOpen aria-hidden="true"/>{pending?'여는 중…':'스터디로 읽기'}</Button>
}
