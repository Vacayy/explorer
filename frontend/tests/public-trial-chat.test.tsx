import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { TrialChatMessage } from '@/types/trialChat'

const state = vi.hoisted(() => ({
  scope: null as null | { id: number; role: string },
  chat: { session: { remaining: 3, limit: 3, csrf_token: 'synthetic' } as null | { remaining: number; limit: number; csrf_token: string },
    messages: [] as TrialChatMessage[], loading: false, sending: false, error: null as string | null,
    send: vi.fn(), reset: vi.fn() },
  docs: { data: { items: [] as { id: number; title: string; snippet: string }[], next_cursor: null as string | null },
    error: null as Error | null, isFetching: false, fetchStatus: 'idle', refetch: vi.fn() },
  initial: { data: undefined as undefined | { id: number; title: string }, error: null as Error | null, isFetching: false, refetch: vi.fn() },
}))
vi.mock('@/components/auth/MemberAccess', () => ({ useMemberAccess: () => ({ status: state.scope ? 'member' : 'anonymous', session: { user: state.scope } }) }))
vi.mock('@/hooks/useTrialChat', () => ({ useTrialChat: () => state.chat }))
vi.mock('@/hooks/usePublishedDocuments', () => ({ usePublishedDocuments: () => state.docs }))
vi.mock('@/hooks/usePublishedDocument', () => ({ usePublishedDocument: () => state.initial }))
const { PublicTrialChatPage } = await import('@/components/chat/PublicTrialChatPage')
const page = (path='/chat') => <MemoryRouter initialEntries={[path]}><PublicTrialChatPage /></MemoryRouter>
beforeEach(() => {
  state.scope=null; state.chat.session={remaining:3,limit:3,csrf_token:'synthetic'}; state.chat.messages=[]
  state.chat.loading=false; state.chat.sending=false; state.chat.error=null; state.chat.send.mockResolvedValue(true)
  state.docs.data={items:Array.from({length:5},(_,i)=>({id:i+1,title:`자료 ${i+1}`,snippet:'공개 본문'})),next_cursor:null}
  state.docs.error=null; state.docs.isFetching=false; state.initial.data=undefined; state.initial.error=null
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('requires a document, caps selection at four, and sends explicit context with a natural question', async () => {
  render(page('/chat?q=never-prefill'))
  expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe('')
  fireEvent.change(screen.getByLabelText('질문'), {target:{value:'매출이 어떻게 변했나요?'}})
  expect((screen.getByRole('button',{name:'질문 보내기'}) as HTMLButtonElement).disabled).toBe(true)
  for(let i=1;i<=4;i++)fireEvent.click(screen.getByRole('checkbox',{name:`자료 ${i}`}))
  expect((screen.getByRole('checkbox',{name:'자료 5'}) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button',{name:'질문 보내기'}))
  await waitFor(()=>expect(state.chat.send).toHaveBeenCalledWith('매출이 어떻게 변했나요?',{document_ids:[1,2,3,4],search_query:''}))
})

it('seeds a deep link only after public validation and clears draft/selection on account change', async () => {
  const view=render(page('/chat?doc=1'))
  expect(screen.getByText('선택한 자료 0/4')).toBeTruthy()
  state.initial.data={id:1,title:'승인 문서'}; view.rerender(page('/chat?doc=1'))
  await screen.findByText('선택한 자료 1/4')
  fireEvent.change(screen.getByLabelText('질문'),{target:{value:'private draft canary'}})
  state.scope={id:42,role:'member'};view.rerender(page('/chat?doc=1'))
  await screen.findByText('선택한 자료 0/4')
  expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe('')
})

it('renders partial model text literally and only allows internal document citations', () => {
  state.chat.messages=[{role:'assistant',content:'<img src="https://invalid.test/tracker"> [link](https://evil.test)',partial:true,
    citations:[{id:'D1',title:'approved',url:'/doc/1'},{id:'D2',title:'unsafe',url:'https://evil.test'}]}]
  render(page())
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.getByText(/<img src=/)).toBeTruthy()
  expect(screen.getByText(/일부 자료를 발췌/)).toBeTruthy()
  expect(screen.getByRole('link',{name:'D1 · approved'}).getAttribute('href')).toBe('/doc/1')
  expect(screen.queryByRole('link',{name:/unsafe/})).toBeNull()
})

it('shows exhausted quota with login without promising a reset', () => {
  state.chat.session!.remaining=0;render(page())
  expect(screen.getByText('체험 횟수를 모두 사용했습니다.')).toBeTruthy()
  expect(screen.getByRole('link',{name:'Google 로그인'})).toBeTruthy()
  expect(screen.getByText(/로그인해도 체험 횟수가 초기화되지는/)).toBeTruthy()
  expect((screen.getByRole('button',{name:'질문 보내기'}) as HTMLButtonElement).disabled).toBe(true)
})

it('distinguishes loading, continuing empty results, and request errors without losing draft', async () => {
  state.docs.isFetching=true;state.chat.loading=true
  const view=render(page())
  expect(screen.getByText('공개 자료를 불러오는 중…')).toBeTruthy()
  state.docs.isFetching=false;state.chat.loading=false;state.docs.data={items:[],next_cursor:'opaque'}
  view.rerender(page())
  expect(screen.getByText(/이 구간에는 일치하는 자료가 없습니다/)).toBeTruthy()
  expect(screen.getByRole('button',{name:'다음 자료'})).toBeTruthy()
  fireEvent.change(screen.getByLabelText('질문'),{target:{value:'draft'}})
  state.chat.error='공개 자료가 변경되어 답변을 제공할 수 없습니다. 다시 질문해 주세요.'
  view.rerender(page())
  expect(screen.getByRole('alert')).toBeTruthy()
  expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe('draft')
  fireEvent.click(screen.getByRole('button',{name:'대화 지우기'}))
  expect(state.chat.reset).toHaveBeenCalledOnce()
  expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe('')
})
