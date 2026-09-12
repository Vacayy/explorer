import { ResearchResults } from './ResearchResults'
import { ResearchMode, type ResearchScope } from './ResearchMode'
import { createPortal } from 'react-dom'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Highlighter, MessageSquarePlus, MousePointer2, Sparkles, ArrowLeft, Send, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { PageLayout, PageHeader } from '@/components/shared/PageLayout'
import { Markdown } from '@/components/shared/Markdown'
import { ErrorState } from '@/components/shared/ErrorState'
import SegmentTabs from '@/components/shared/SegmentTabs'
import { citationComponents, linkifyCitations } from '@/components/chat/citations'
import type { ChatMessage } from '@/types'
import { type Annotation, errorMessage, useStudy } from './useStudy'

type Selection={start:number;end:number;exact:string}
type Mode='read'|'highlight'|'comment'
export default function StudyPage(){const {id}=useParams();return <StudyWorkspace key={id} id={Number(id)}/>}
export function StudyWorkspace({id, embedded, active=true, unifiedNotes=false, noteHost, initialPicked, history, onNotes, onAsk, onSelection, onDirty}: {id:number; embedded?:boolean; active?:boolean; unifiedNotes?:boolean; noteHost?:HTMLElement|null; initialPicked?:number[]; history?:Annotation[]; onNotes?:()=>void; onAsk?:(id:number,annotations:Annotation[],question:string)=>void; onSelection?:(id:number,annotations:Annotation[])=>void; onDirty?:(id:number,dirty:boolean)=>void}){
 const q=useStudy(id),cache=useQueryClient(),s=q.data
 const [params,setParams]=useSearchParams()
 const [mode,setMode]=useState<Mode>('read'),[panel,setPanel]=useState('notes'),[mobile,setMobile]=useState('read')
 const [dirtyIds,setDirtyIds]=useState<number[]>([])
 const [picked,setPicked]=useState<number[]>([]),[pending,setPending]=useState<Selection|null>(null),[comment,setComment]=useState('')
 const [research,setResearch]=useState<ResearchScope>('auto'),[includeBody,setIncludeBody]=useState(false)
 const [question,setQuestion]=useState(''),[busy,setBusy]=useState(false),[saving,setSaving]=useState(false)
 const requestRef=useRef<{signature:string;key:string}|null>(null)
 const savingRef=useRef(false),textRef=useRef<HTMLDivElement>(null),readerRef=useRef<HTMLElement>(null),chatRef=useRef<HTMLDivElement>(null),restored=useRef(false)
 const pickedRestored=useRef(false)
 useEffect(()=>{if(s&&!pickedRestored.current){const prior=embedded?(initialPicked??[]):s.turns.some(t=>t.status==='complete')?[]:(s.turns.at(-1)?.context.annotations??[]).map(a=>a.id);setPicked(prior.filter(id=>s.annotations.some(a=>a.id===id)));pickedRestored.current=true}},[s])
 const refs=useMemo(()=>s?.annotations.filter(a=>picked.includes(a.id))??[],[s?.annotations,picked])
 useEffect(()=>{onSelection?.(id,refs)},[id,refs,onSelection])
 useEffect(()=>{onDirty?.(id,!!dirtyIds.length||!!(pending&&comment.trim()))},[id,dirtyIds,pending,comment,onDirty])
 const continuing=!!s?.turns.some(t=>t.status==='complete')&&!refs.length&&!includeBody
 const generating=s?.turns.some(t=>t.status==='pending')??false
 const conv=useQuery({queryKey:['spine','study-chat',s?.conversation_id],queryFn:async()=>(await api.get<{messages:ChatMessage[]}>(`/api/spine/conversations/${s!.conversation_id}`)).data,enabled:!!s?.conversation_id,refetchInterval:generating?1500:false})
 useEffect(()=>{if(s?.conversation_id)void cache.invalidateQueries({queryKey:['spine','study-chat',s.conversation_id]})},[s?.conversation_id,s?.turns.at(-1)?.status,cache])
 const chars=useMemo(()=>Array.from(s?.body??''),[s?.body])
 const blocks=useMemo(()=>{const out:{text:string;start:number;end:number}[]=[];let pos=0;for(const match of (s?.body??'').matchAll(/[^\n]*\n|[^\n]+$/g)){const text=match[0],end=pos+Array.from(text).length;out.push({text,start:pos,end});pos=end}return out},[s?.body])
 useEffect(()=>{if(s&&active&&!restored.current&&readerRef.current){try{readerRef.current.scrollTop=Number(sessionStorage.getItem(`study-position-${id}`)||0)}catch{/* storage unavailable */}restored.current=true}},[s,id,active])
 useEffect(()=>{const target=Number(params.get('annotation'));if(s&&target&&active){setMobile('read');requestAnimationFrame(()=>textRef.current?.querySelector(`[data-annotation~="${target}"]`)?.scrollIntoView({block:'center'}))}},[params,s?.id,active])
 useEffect(()=>{if(panel==='chat')chatRef.current?.scrollTo({top:chatRef.current.scrollHeight,behavior:'smooth'})},[conv.data?.messages.length,panel])
 useEffect(()=>{const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'){setMode('read');setPending(null)}};document.addEventListener('keydown',onKey);return()=>document.removeEventListener('keydown',onKey)},[])
 async function reload(){await q.refetch();await cache.invalidateQueries({queryKey:['spine','studies']});if(s?.project_id)await cache.invalidateQueries({queryKey:['spine','study-project',s.project_id]})}
 function side(value:string){if(embedded){if(value==='chat'){onAsk?.(id,refs,question||'선택한 부분과 내 코멘트를 함께 보고 설명해 주세요.');return}onNotes?.()}setPanel(value);setMobile(value)}
 function selection():Selection|null{const el=textRef.current,sel=window.getSelection();if(!el||!sel?.rangeCount||!sel.toString().trim()||!el.contains(sel.anchorNode)||!el.contains(sel.focusNode))return null;const r=sel.getRangeAt(0),pre=r.cloneRange();pre.selectNodeContents(el);pre.setEnd(r.startContainer,r.startOffset);const start=Array.from(pre.toString()).length,exact=r.toString();return{start,end:start+Array.from(exact).length,exact}}
 async function add(sel:Selection,kind:'highlight'|'comment',note=''){
  if(savingRef.current)return;savingRef.current=true;setSaving(true)
  try{const {data}=await api.post<Annotation>(`/api/spine/studies/${id}/annotations`,{...sel,kind,comment:note});setPicked(p=>[...p,data.id]);await reload();setPending(null);setComment('');window.getSelection()?.removeAllRanges();toast.success(kind==='highlight'?'하이라이트 저장됨':'코멘트 저장됨')}
  catch(e){toast.error(errorMessage(e))}finally{savingRef.current=false;setSaving(false)}
 }
 function applySelection(){const sel=selection();if(!sel)return;if(mode==='highlight')void add(sel,'highlight');else if(mode==='comment'){setPending(sel);setComment('');side('notes')}}
 function clickText(e:React.MouseEvent){
  if(mode==='read'){const ids=(e.target as HTMLElement).closest('[data-annotation]')?.getAttribute('data-annotation')?.split(' ').filter(Boolean).map(Number)??[];if(ids.length){setPicked(ids);side('notes')}return}
  if(mode!=='comment')return
  const sel=selection();if(sel){setPending(sel);setComment('');side('notes');return}
  const el=textRef.current;if(!el)return
  const dom=document as Document & {caretRangeFromPoint?:(x:number,y:number)=>Range|null;caretPositionFromPoint?:(x:number,y:number)=>{offsetNode:Node;offset:number}|null}
  let r=dom.caretRangeFromPoint?.(e.clientX,e.clientY)
  if(!r){const p=dom.caretPositionFromPoint?.(e.clientX,e.clientY);if(p){r=document.createRange();r.setStart(p.offsetNode,p.offset);r.collapse(true)}}
  let start=Number((e.target as HTMLElement).closest('[data-block-start]')?.getAttribute('data-block-start')??0)
  if(r&&el.contains(r.startContainer)){const pre=r.cloneRange();pre.selectNodeContents(el);pre.setEnd(r.startContainer,r.startOffset);start=Array.from(pre.toString()).length}
  let a=Math.min(start,chars.length-1),b=a;while(a>0&&!/[\n.!?。]/.test(chars[a-1]))a--;while(b<chars.length&&!/[\n.!?。]/.test(chars[b]))b++;if(b<chars.length)b++
  const exact=chars.slice(a,b).join('');if(exact.trim()){setPending({start:a,end:b,exact});setComment('');side('notes')}
 }
 function jump(a:Annotation){setMobile('read');setParams(p=>{p.set('annotation',String(a.id));if(embedded)p.set('doc',String(id));return p},{replace:true});requestAnimationFrame(()=>textRef.current?.querySelector(`[data-annotation~="${a.id}"]`)?.scrollIntoView({block:'center',behavior:'smooth'}))}
 async function send(action:'question'|'summarize',annotations=refs){
  if(busy||generating||!s)return
  if(dirtyIds.length||(pending&&comment.trim())){toast('작성 중인 코멘트를 먼저 저장해 주세요.');side('notes');return}
  if(action==='question'&&!question.trim()){toast('질문을 입력해 주세요.');return}
  if(action==='summarize'&&!annotations.length){toast('요약할 하이라이트를 선택해 주세요.');return}
  if(embedded){onAsk?.(id,annotations,action==='summarize'?'선택한 하이라이트의 핵심을 요약하고 출처별 관점 차이를 설명해 주세요.':question);return}
  setBusy(true);side('chat')
  const payload={research,context_mode:action==='question'&&continuing?'continue':'selection',question:action==='summarize'?'선택한 하이라이트의 핵심을 요약하고, 내가 남긴 생각과 궁금증을 구분해서 설명해 주세요.':question,action,annotations:annotations.map(a=>({id:a.id,revision:a.revision}))}
  const signature=JSON.stringify(payload)
  if(requestRef.current?.signature!==signature)requestRef.current={signature,key:crypto.randomUUID()}
  try{await api.post(`/api/spine/studies/${id}/ask`,{...payload,request_key:requestRef.current.key});requestRef.current=null;setQuestion('');setPicked([]);setIncludeBody(false);await reload();if(s.conversation_id)await conv.refetch()}
  catch(e){toast.error(errorMessage(e))}finally{setBusy(false)}
 }
 if(!Number.isInteger(id)||id<1)return <ErrorState message="올바르지 않은 스터디 주소입니다."/>
 if(q.isLoading)return <p className="p-6 text-sm text-muted-foreground">스터디를 불러오는 중…</p>
 if(q.isError||!s)return <ErrorState message="스터디를 불러올 수 없습니다." onRetry={()=>q.refetch()}/>
 const historicalId=Number(params.get('annotation'))
 const historical=s.annotations.some(a=>a.id===historicalId)?undefined:[...s.turns.flatMap(t=>t.context.annotations),...(history??[])].find(a=>a.id===historicalId)
 const displayedAnnotations=historical?[...s.annotations,historical]:s.annotations
 const selectedHighlights=(refs.length?refs:s.annotations).filter(a=>a.kind==='highlight')
 const Frame=embedded?StudyFrame:PageLayout
 return <TooltipProvider><Frame header={<PageHeader title={s.title} description={`스터디 · ${s.body_kind} · 고정 본문`} actions={<><Button variant="ghost" size="sm" asChild><Link to={s.document_id?`/doc/${s.document_id}`:`/study/projects/${s.project_id}`}><ArrowLeft/>문서 상세</Link></Button><Button variant="ghost" size="sm" asChild><Link to="/study">스터디 목록</Link></Button></>}/> }>
 <div className="study-workspace" data-panel={mobile}>
  <div className="study-palette" role="toolbar" aria-label="스터디 도구 팔레트">
   {([{key:'read',label:'읽기',Icon:MousePointer2},{key:'highlight',label:'하이라이트',Icon:Highlighter},{key:'comment',label:'코멘트',Icon:MessageSquarePlus}] as const).map(t=><Button key={t.key} variant={mode===t.key?'secondary':'ghost'} size="sm" aria-pressed={mode===t.key} onClick={()=>{setMode(t.key);setMobile('read')}}><t.Icon aria-hidden="true"/>{t.label}</Button>)}
   <span className="text-caption text-muted-foreground">{saving?'저장 중…':mode==='highlight'?'드래그하면 표시 · Esc로 읽기':mode==='comment'?'문장을 클릭하면 코멘트':'표시한 문장을 눌러 위치 확인'}</span>
   {mode==='highlight'&&<Button size="sm" variant="ghost" onClick={applySelection}>선택 영역 표시</Button>}
   {embedded&&<Button size="sm" variant="ghost" onClick={()=>side('notes')}>노트 {s.annotations.length}</Button>}
   <Button className="ml-auto" size="sm" variant="outline" disabled={busy||generating||!selectedHighlights.length} onClick={()=>send('summarize',selectedHighlights)}><Sparkles aria-hidden="true"/>하이라이트 요약</Button>
  </div>
  <div className="study-mobile-tabs"><SegmentTabs tabs={[{value:'read',label:'문서'},{value:'notes',label:`노트 ${s.annotations.length}`},{value:'chat',label:'AI 대화'}]} value={mobile} onChange={v=>{setMobile(v);if(v!=='read')setPanel(v)}}/></div>
  <div className="study-columns">
   <article className="study-reader" aria-label="스터디 원문" ref={readerRef} onScroll={()=>{if(!active)return;try{sessionStorage.setItem(`study-position-${id}`,String(readerRef.current?.scrollTop??0))}catch{/* private storage */}}}>
    <p className="mb-5 text-caption text-muted-foreground">{s.source_type} · {s.body_kind} · 주석을 보존하기 위해 처음 연 본문을 유지합니다.</p>
    {historical&&<p className="mb-3 text-caption text-muted-foreground">삭제된 주석의 당시 위치를 표시합니다. 인용과 코멘트는 대화 이력에 보존돼 있습니다.</p>}
    <div ref={textRef} className="study-text" data-tool={mode} onPointerUp={()=>{if(mode==='highlight')setTimeout(applySelection,0)}} onClick={clickText}>
     {blocks.map(block=>{const marks=displayedAnnotations.filter(a=>a.start_offset<block.end&&a.end_offset>block.start);const cuts=[...new Set([block.start,block.end,...marks.flatMap(a=>[Math.max(block.start,a.start_offset),Math.min(block.end,a.end_offset)])])].sort((a,b)=>a-b);return <div key={block.start} data-block-start={block.start} tabIndex={mode==='comment'?0:undefined} onKeyDown={e=>{if(mode==='comment'&&e.key==='Enter'){e.preventDefault();setPending({start:block.start,end:block.end,exact:block.text});setComment('');side('notes')}}}>{cuts.slice(0,-1).map((start,i)=>{const end=cuts[i+1],active=marks.filter(a=>a.start_offset<end&&a.end_offset>start),highlight=active.some(a=>a.kind==='highlight'),note=active.some(a=>a.comment||a.kind==='comment');return <span key={start} data-annotation={active.map(a=>a.id).join(' ')} className={`${highlight?'study-highlight ':''}${note?'study-comment-anchor ':''}${active.some(a=>picked.includes(a.id))?'study-picked':''}`} title={active.map(a=>a.comment).filter(Boolean).join('\n')}>{chars.slice(start,end).join('')}</span>})}</div>})}
    </div>
    {/^https?:\/\//i.test(s.source_url||'')&&<a href={s.source_url} target="_blank" rel="noreferrer" className="mt-6 block text-caption text-primary underline">원문 사이트 ↗</a>}
   </article>
   <StudyAside embedded={embedded} active={unifiedNotes||active} host={noteHost}><aside className="study-aside" aria-label="스터디 노트와 AI 대화">
    <div className="study-panel-header" hidden={unifiedNotes}>{embedded?<h2 className="text-sm font-semibold">문서의 하이라이트와 코멘트</h2>:<SegmentTabs tabs={[{value:'notes',label:`노트 ${s.annotations.length}`},{value:'chat',label:'AI 대화'}]} value={panel} onChange={side}/>}</div>
    {embedded||panel==='notes'?<div className="study-notes">
     {pending&&<section className="study-note"><h2 className="text-sm font-semibold">이 문장에 코멘트</h2>{unifiedNotes&&<p className="text-caption text-muted-foreground">{s.title}</p>}<blockquote className="my-2 text-sm text-muted-foreground">{pending.exact}</blockquote><Textarea autoFocus value={comment} onChange={e=>setComment(e.target.value)} maxLength={10000} aria-label="새 코멘트" placeholder="어떤 생각이나 궁금증이 들었나요?"/><div className="mt-2 flex gap-2"><Button size="sm" disabled={saving||!comment.trim()} onClick={()=>add(pending,'comment',comment)}>코멘트 저장</Button><Button size="sm" variant="ghost" onClick={()=>setPending(null)}>취소</Button></div></section>}
     {!unifiedNotes&&<p className="text-caption text-muted-foreground">체크한 주석과 저장된 코멘트를 AI에 함께 보냅니다.</p>}
     {!unifiedNotes&&!s.annotations.length&&!pending&&<p className="py-6 text-sm text-muted-foreground">팔레트에서 하이라이트를 선택하고 드래그하거나, 코멘트를 선택하고 문장을 클릭해 보세요.</p>}
     {s.annotations.map(a=><AnnotationEditor key={a.id} annotation={a} sourceTitle={unifiedNotes?s.title:undefined} studyId={id} onDirty={dirty=>setDirtyIds(p=>dirty?[...new Set([...p,a.id])]:p.filter(x=>x!==a.id))} picked={picked.includes(a.id)} onPick={v=>setPicked(p=>v?[...p,a.id]:p.filter(x=>x!==a.id))} onJump={()=>jump(a)} onSaved={reload} onAsk={()=>{if(embedded){onAsk?.(id,[a],'이 문장과 내 코멘트를 설명해 주세요.');return}setPicked([a.id]);setQuestion('이 문장에서 내가 남긴 코멘트를 바탕으로 궁금한 점을 설명해 주세요.');side('chat')}}/>)}
     {refs.length>0&&<Button variant="outline" size="sm" className="w-full" onClick={()=>{side('chat');setQuestion('선택한 부분과 내 코멘트를 함께 보고 설명해 주세요.')}}><Send/>선택한 코멘트·주석을 AI에 넘기기</Button>}
    </div>:<>
     <div className="study-chat" ref={chatRef} aria-live="polite">
      {!s.conversation_id&&<p className="text-sm text-muted-foreground py-4">문서를 보며 질문하세요. 하이라이트와 코멘트가 대화의 근거가 됩니다.</p>}
      {conv.isError&&<Button size="sm" variant="outline" onClick={()=>conv.refetch()}>대화 다시 불러오기</Button>}
      {conv.data?.messages.map((m,index)=><div key={m.id} className={`study-message ${m.role==='user'?'study-question':''}`}><p className="text-caption text-muted-foreground mb-2">{m.role==='user'?'나':'AI · 학습 도우미'}</p><Markdown components={citationComponents(m.citations??null)}>{linkifyCitations(m.content,m.citations??null)}</Markdown>{m.role==='assistant'&&<ResearchResults research={s.turns.find(t=>t.message_id===conv.data?.messages[index-1]?.id)?.context.research}/>}{m.role==='user'&&s.turns.find(t=>t.message_id===m.id)&&<details className="mt-2 text-caption text-muted-foreground"><summary>이 질문에 사용한 자료</summary><p>{s.turns.find(t=>t.message_id===m.id)?.context.scope}</p>{s.turns.find(t=>t.message_id===m.id)?.context.annotations.map(a=><div key={a.id} className="my-2"><p>{a.exact}</p>{a.comment&&<p>내 코멘트: {a.comment}</p>}</div>)}</details>}</div>)}
      {(busy||generating)&&<p role="status" className="text-sm text-muted-foreground">선택한 자료를 읽고 답변하는 중…</p>}
      {s.turns.filter(t=>t.status==='pending'&&Date.now()-Date.parse(t.created_at.replace(' ','T')+'Z')>600000).map(t=><Button key={t.id} size="sm" variant="outline" onClick={async()=>{try{await api.post(`/api/spine/studies/${id}/turns/${t.id}/recover`);await reload();await conv.refetch()}catch(e){toast.error(errorMessage(e))}}}>멈춘 요청 정리하고 다시 질문하기</Button>)}
      {s.turns.at(-1)?.status==='error'&&<p role="alert" className="text-sm text-destructive">답변을 완료하지 못했습니다. 질문을 다시 보내 재시도할 수 있습니다.</p>}
     </div>
     <div className="study-composer"><ResearchMode value={research} onChange={setResearch}/>{s.turns.some(t=>t.status==='complete')&&<label className="flex gap-2 text-caption mb-2"><Checkbox checked={includeBody} onCheckedChange={v=>setIncludeBody(v===true)}/>현재 본문 다시 포함</label>}
      <details className="text-caption text-muted-foreground mb-2"><summary>함께 보낼 내용 · {continuing?'이전 대화 이어가기 · 주석 재첨부 없음':refs.length?`주석 ${refs.length}개와 코멘트`:(chars.length>16000?'본문 앞 16,000자':'본문 전체')}</summary>{refs.map(a=><label key={a.id} className="flex gap-2 my-2"><Checkbox checked onCheckedChange={()=>setPicked(p=>p.filter(x=>x!==a.id))}/><span>{a.exact.slice(0,100)}{a.comment&&<span className="block">내 코멘트: {a.comment}</span>}</span></label>)}<p>질문에 따라 관련 수집 자료를 찾거나 웹 근거를 확인합니다. 새로 선택한 주석만 다시 첨부합니다.</p></details>
      <Textarea aria-label="스터디 질문" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={4000} placeholder="내가 표시한 부분을 더 쉽게 설명해줘" onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();void send('question')}}}/>
      <div className="mt-2 flex justify-between gap-2">{s.conversation_id?<Link to={`/chat?id=${s.conversation_id}`} className="text-caption text-muted-foreground self-center">대화 이력에서 보기 ↗</Link>:<span className="text-caption text-muted-foreground">대화 이력에도 저장됩니다</span>}<Button size="sm" disabled={busy||generating||!question.trim()} onClick={()=>send('question')}><Send aria-hidden="true"/>보내기</Button></div>
     </div>
    </>}
   </aside></StudyAside>
  </div>
 </div>
 </Frame></TooltipProvider>
}
function StudyFrame({children}:{children:React.ReactNode;header?:React.ReactNode}){return <div className="project-study-reader">{children}</div>}
function StudyAside({embedded,active,host,children}:{embedded?:boolean;active:boolean;host?:HTMLElement|null;children:React.ReactNode}){return embedded?(host?createPortal(<div className="project-document-notes" hidden={!active}>{children}</div>,host):null):children}
function AnnotationEditor({annotation:a,sourceTitle,studyId,picked,onPick,onJump,onSaved,onAsk,onDirty}:{annotation:Annotation;sourceTitle?:string;studyId:number;picked:boolean;onPick:(v:boolean)=>void;onJump:()=>void;onSaved:()=>Promise<void>;onAsk:()=>void;onDirty:(dirty:boolean)=>void}){
 const [draft,setDraft]=useState(a.comment),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const dirty=draft!==a.comment
 async function save(remove=false){setBusy(true);setError('');try{await api.patch(`/api/spine/studies/${studyId}/annotations/${a.id}`,{revision:a.revision,comment:draft,delete:remove});onDirty(false);await onSaved()}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
 return <section className="study-note">{sourceTitle&&<Button variant="secondary" size="xs" className="study-source-tag" title={sourceTitle} aria-label={`${sourceTitle} 인용 위치로 이동`} onClick={onJump}>{sourceTitle}</Button>}<div className="flex items-start gap-2"><Checkbox aria-label={`AI에 포함 주석 ${a.id}`} checked={picked} onCheckedChange={v=>onPick(v===true)}/><Button variant="ghost" className="h-auto min-w-0 flex-1 whitespace-normal text-left justify-start p-0 text-sm font-normal" onClick={onJump}>{a.exact}</Button></div><Textarea className="mt-3" aria-label={`코멘트 ${a.id}`} value={draft} onChange={e=>{setDraft(e.target.value);onDirty(e.target.value!==a.comment)}} maxLength={10000} placeholder="내 생각이나 궁금증을 남기세요"/><div className="mt-2 flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy||!dirty} onClick={()=>save()}>{busy?'저장 중…':dirty?'코멘트 저장':'저장됨'}</Button><Button size="sm" variant="ghost" disabled={busy||dirty} onClick={onAsk}>AI에 넘기기</Button><Button size="icon-sm" variant="ghost" className="ml-auto" aria-label={`주석 ${a.id} 삭제`} disabled={busy} onClick={()=>save(true)}><Trash2 aria-hidden="true"/></Button></div>{dirty&&<p className="text-caption text-muted-foreground mt-1">저장 후 AI에 넘길 수 있습니다.</p>}{error&&<p role="alert" className="text-caption text-destructive mt-1">{error} 입력 내용은 유지됩니다.</p>}</section>
}
