import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import api from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
export function StudyList(){
 const q=useQuery({queryKey:['spine','studies'],queryFn:async()=>(await api.get<{id:number;title:string;annotation_count:number}[]>('/api/spine/studies')).data})
 return <Card><CardHeader><CardTitle className="text-base">이어서 공부하기</CardTitle></CardHeader><CardContent className="space-y-2">
 {q.isLoading?<p className="text-sm text-muted-foreground">스터디 불러오는 중…</p>:q.isError?<Button variant="outline" size="sm" onClick={()=>q.refetch()}>다시 불러오기</Button>:q.data?.length?q.data.slice(0,8).map(s=><Link key={s.id} to={`/study/${s.id}`} className="flex justify-between gap-3 rounded-lg p-2 text-sm hover:bg-muted"><span className="truncate">{s.title}</span><span className="shrink-0 text-caption text-muted-foreground">주석 {s.annotation_count}</span></Link>):<p className="text-sm text-muted-foreground">피드나 문서에서 ‘스터디로 읽기’를 눌러 시작하세요.</p>}
 </CardContent></Card>
}
