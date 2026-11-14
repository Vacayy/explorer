import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AssistantMessage } from '../src/components/chat/AssistantMessage'
import { Composer } from '../src/components/chat/Composer'
import { evidenceSummary } from '../src/components/chat/RoutePanel'
import { answerClipText, citedDocIds } from '../src/hooks/useChatStudy'
import { formatKstSlashDate } from '../src/utils/format'
import type { ChatMessage, ChatRoute } from '../src/types'

// AI 대화 · 검색 시안 정렬(ia-redesign §4.14, 개편 4j) — 고정 대화로만 확인한다(질문 전송·LLM 없음)
afterEach(() => cleanup())
// jsdom에는 matchMedia가 없다 — 데스크톱 폭으로 둔다
window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia

const route: ChatRoute = {
  intent: 'synthesis', standalone_question: null, entities: null, lens: null, answer_style: null, evidence_n: 14,
  timings_ms: { route: 5000, synth: 60000 }, model: 'claude-code/sonnet',
  tools: [
    { name: 'get_quote', n: 1 }, { name: 'list_recent', args: { kind: 'disclosures' }, n: 5 }, { name: 'search_docs', n: 8 },
    { name: 'get_lens', n: 0 }, { name: 'get_lens', n: 0, error: '실패' },
  ],
}
const answer: ChatMessage = {
  id: 501, role: 'assistant', model: 'claude-code/sonnet', created_at: '2026-11-02 23:13:53', route,
  content: '**결론:** 후공정 장비주로 읽힙니다[1].\n\n본문[7]',
  citations: [
    { n: 1, kind: 'quote', title: '실시간 시세 (답변 시점)', doc_id: null },
    { n: 2, kind: 'disclosure', title: '주식등의대량보유상황보고서 · 20261002', doc_id: null },
    { n: 7, kind: 'doc', title: '[루팡] DS투자증권', doc_id: 16705, href: '/doc/16705', published_at: '2026-09-06T23:30:07+00:00' },
  ],
  gaps: [{ type: 'contradiction', note: '추정치가 다름' }, { type: 'missing', note: '3분기 실적 없음' }],
}

it('sums tool calls into evidence groups — same tool once, errors count 0', () => {
  expect(evidenceSummary(route)).toEqual(['시세 1건', '최근 공시 5건', '문서 검색 8건', '투자 렌즈 0건'])
})

it('formats KST slash dates for list rows and answer heads', () => {
  expect(formatKstSlashDate('2026-11-02 23:13:53')).toBe('11/03 08:13')
  expect(formatKstSlashDate('2026-11-02 23:13:53', false)).toBe('11/03')
  expect(formatKstSlashDate('2026-11-04', false)).toBe('11/04')
  expect(formatKstSlashDate(null)).toBe('-')
})

it('collects cited documents once and builds an answer clip with sources', () => {
  expect(citedDocIds([answer, { ...answer, citations: [{ n: 1, title: 'x', doc_id: 16705 }, { n: 2, title: 'y', doc_id: 9 }] }])).toEqual([16705, 9])
  expect(answerClipText(answer)).toContain('\n\n출처\n[1] 실시간 시세 (답변 시점)\n[2]')
})

function renderAnswer(props: Partial<Parameters<typeof AssistantMessage>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter>
    <AssistantMessage m={answer} isLast conversationId={75} threadTitle="피에스케이홀딩스 리서치" {...props} />
  </MemoryRouter></QueryClientProvider>)
}

it('answer: AI badge · evidence summary · short model · actions · gap and source boxes', () => {
  const onRegenerate = vi.fn()
  renderAnswer({ onRegenerate })
  expect(screen.getByText('AI 답변')).toBeTruthy()
  expect(screen.getByText(/근거 수집 · 시세 1건 · 최근 공시 5건 · 문서 검색 8건 · 투자 렌즈 0건/)).toBeTruthy()
  expect(screen.getByText(/sonnet · 11\/03 08:13/)).toBeTruthy()
  const actions = document.querySelector('[data-answer-actions]') as HTMLElement
  expect(within(actions).getAllByRole('button').map(b => b.textContent?.trim())).toEqual(['복사', '저장', '스터디로 보내기', '다시 답변'])
  within(actions).getByText('다시 답변').click()
  expect(onRegenerate).toHaveBeenCalledOnce()
  expect(screen.getByText('이 답에서 확인하지 못한 것')).toBeTruthy()
  expect(screen.getByText('자료끼리 엇갈림')).toBeTruthy()
  expect(screen.getByText('근거 없음')).toBeTruthy()
  expect(screen.getByText('출처 3')).toBeTruthy()
  const doc = document.querySelector('[data-source="7"]') as HTMLElement
  expect(doc.textContent).toContain('자료')
  expect(doc.textContent).toContain('09/07')
  expect(within(doc).getByRole('link').getAttribute('href')).toBe('/doc/16705')
  expect(document.querySelector('[data-source="1"]')!.textContent).toContain('11/03')
  expect(document.querySelector('[data-source="2"]')!.textContent).toContain('공시')
})

it('answer without conversation/title/regenerate hides save, study and regenerate', () => {
  renderAnswer({ conversationId: null, threadTitle: null })
  const actions = document.querySelector('[data-answer-actions]') as HTMLElement
  expect(within(actions).getAllByRole('button').map(b => b.textContent?.trim())).toEqual(['복사'])
})

it('composer: attachment chip row only when given, no caption line, send button', () => {
  const { rerender } = render(<Composer value="" onChange={() => {}} onSubmit={() => {}} busy={false} placeholder="이어서 물어보기" />)
  expect(document.querySelector('[data-composer-attachments]')).toBeNull()
  expect(screen.queryByText(/Enter 전송/)).toBeNull()
  expect(screen.getByRole('button', { name: '질문 보내기' }).textContent).toBe('보내기')
  rerender(<Composer value="" onChange={() => {}} onSubmit={() => {}} busy={false} placeholder="p" attachments={<span>보고 있는 화면 · 홈</span>} />)
  expect(within(document.querySelector('[data-composer-attachments]') as HTMLElement).getByText('보고 있는 화면 · 홈')).toBeTruthy()
})
