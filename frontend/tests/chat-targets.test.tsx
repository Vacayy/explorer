import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import api from '../src/api/client'
import { askQuestion } from '../src/api/spine'
import { Composer } from '../src/components/chat/Composer'
import { TargetChip } from '../src/components/chat/TargetChip'
import { addTarget, findAtQuery, MAX_TARGETS, removeAtQuery, toPayload } from '../src/lib/chatTargets'
import type { ChatTarget } from '../src/types'

// AI 대화 › 대상 붙이기 (ia-redesign §4.14a, D-311) — 질문 전송·LLM 없음, 후보는 고정 데이터
const HYNIX: ChatTarget = { kind: 'stock', ref: '000660', label: 'SK하이닉스', code: '000660', change_pct: 2.1, sub: '000660 · 반도체 · KOSPI' }
const HYNIX_PREF: ChatTarget = { kind: 'stock', ref: '000665', label: 'SK하이닉스우', code: '000665', change_pct: 1.4 }
const HBM: ChatTarget = { kind: 'narrative', ref: 'HBM', label: 'HBM', date: '2026-11-04', sub: 'HBM 공급 우위' }
const Q7: ChatTarget = { kind: 'question', ref: '7', label: '오픈소스 모델 확장', code: '#7' }

const SEARCH = {
  groups: [{ kind: 'stock', items: [HYNIX, HYNIX_PREF] }, { kind: 'narrative', items: [HBM] }, { kind: 'question', items: [Q7] }],
  items: [HYNIX, HYNIX_PREF, HBM, Q7], isLoading: false, isFetching: false, isError: false, isPlaceholderData: false, refetch: () => {},
}
vi.mock('../src/hooks/useChatTargets', () => ({
  targetValue: (t: { kind: string; ref: string }) => `${t.kind}:${t.ref}`,
  useChatTargets: () => SEARCH,   // 결과가 같으면 같은 배열(실제 훅의 useMemo와 같게)
}))

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as typeof window.matchMedia
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= function () {}
})
afterEach(() => cleanup())

it('finds @query only at a word start and removes it after picking', () => {
  expect(findAtQuery('4분기 HBM 정리해줘 @하이', 16)).toEqual({ start: 13, query: '하이' })
  expect(findAtQuery('메일 a@b', 7)).toBeNull()
  expect(findAtQuery('@', 1)).toEqual({ start: 0, query: '' })
  expect(removeAtQuery('정리해줘 @하이', { start: 5, query: '하이' })).toBe('정리해줘 ')
})

it('adds a target once and stops at five sendable targets; vanished ones are dropped from the payload', () => {
  let list: ChatTarget[] = []
  list = addTarget(addTarget(list, HYNIX), HYNIX)
  expect(list).toHaveLength(1)
  for (let i = 0; i < 10; i++) list = addTarget(list, { kind: 'doc', ref: String(i), label: `d${i}` })
  expect(list).toHaveLength(MAX_TARGETS)
  const gone = { ...HBM, available: false }
  expect(toPayload([HYNIX, gone, Q7])).toEqual([
    { kind: 'stock', ref: '000660', label: 'SK하이닉스' }, { kind: 'question', ref: '7', label: '오픈소스 모델 확장' }])
})

it('vanished chip: faded dashed chip without a caption; the reason lives in the tooltip (D-312)', async () => {
  const { container } = render(<TargetChip target={{ ...HBM, available: false }} onRemove={() => {}} />)
  const chip = container.querySelector('[data-target-chip="narrative:HBM"]')!
  expect(chip.getAttribute('data-gone')).toBe('true')
  expect(chip.className).toContain('border-dashed')
  expect(chip.className).toContain('opacity-60')
  expect(chip.textContent).not.toContain('사라짐')
  await act(async () => { fireEvent.focus(screen.getByText('HBM')) })
  expect((await screen.findAllByText(/보관되거나 지워진 대상이라 보낼 때 빠집니다/)).length).toBeGreaterThan(0)
})

function Harness({ initial = [] as ChatTarget[], onTargets = (_: ChatTarget[]) => {} }) {
  const [value, setValue] = useState('')
  const [targets, setTargets] = useState<ChatTarget[]>(initial)
  return <>
    <Composer value={value} onChange={setValue} onSubmit={() => {}} busy={false} placeholder="질문"
      targets={targets} onTargetsChange={t => { setTargets(t); onTargets(t) }} />
    <output data-testid="text">{value}</output>
  </>
}

it('composer: typing @ opens the grouped picker; ↓ Enter attaches a chip and removes the @query', async () => {
  const onTargets = vi.fn()
  render(<Harness onTargets={onTargets} />)
  const input = screen.getByLabelText('질문 입력') as HTMLTextAreaElement
  await act(async () => { fireEvent.change(input, { target: { value: '4분기 HBM 정리해줘 @하이' } }) })
  const picker = document.querySelector('[data-target-picker]') as HTMLElement
  expect(picker).toBeTruthy()
  expect(picker.textContent).toContain('종목')
  expect(picker.textContent).toContain('서사')
  expect(picker.textContent).toContain('리포트')   // kind chips include D-311 kinds
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(onTargets).toHaveBeenLastCalledWith([HYNIX_PREF])
  expect(screen.getByTestId('text').textContent).toBe('4분기 HBM 정리해줘 ')
  expect(document.querySelector('[data-target-chip="stock:000665"]')).toBeTruthy()
  expect(document.querySelector('[data-target-picker]')).toBeNull()
})

it('composer: Esc closes the picker without attaching; chips show code, date and question number', async () => {
  const onTargets = vi.fn()
  render(<Harness initial={[HYNIX, HBM, Q7]} onTargets={onTargets} />)
  const input = screen.getByLabelText('질문 입력')
  await act(async () => { fireEvent.change(input, { target: { value: '@' } }) })
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(document.querySelector('[data-target-picker]')).toBeNull()
  expect(onTargets).not.toHaveBeenCalled()
  expect(document.querySelector('[data-target-chip="stock:000660"]')!.textContent).toContain('000660')
  expect(document.querySelector('[data-target-chip="stock:000660"]')!.textContent).toContain('+2.1%')
  expect(document.querySelector('[data-target-chip="narrative:HBM"]')!.textContent).toContain('11/04')
  expect(document.querySelector('[data-target-chip="question:7"]')!.textContent).toContain('질문 #7')
  fireEvent.click(screen.getByLabelText('HBM 빼기'))
  expect(onTargets).toHaveBeenLastCalledWith([HYNIX, Q7])
})

it('composer: with five targets every candidate is disabled', async () => {
  const five = Array.from({ length: 5 }, (_, i) => ({ kind: 'doc' as const, ref: String(i), label: `자료 ${i}` }))
  const onTargets = vi.fn()
  render(<Harness initial={five} onTargets={onTargets} />)
  fireEvent.click(screen.getByLabelText('대상 붙이기'))
  const items = [...document.querySelectorAll('[data-target-picker] [cmdk-item]')]
  expect(items.length).toBe(4)
  expect(items.every(el => el.getAttribute('aria-disabled') === 'true')).toBe(true)
})

it('ask payload carries attachments as {kind, ref, label}', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { answer: null, citations: [], gaps: [], model: null, conversation_id: 9, status: 'pending', as_of: 'x' } })
  await askQuestion({ question: '정리해줘', attachments: toPayload([HYNIX, HBM]) })
  expect(post.mock.calls[0][1]).toEqual({ question: '정리해줘', attachments: [{ kind: 'stock', ref: '000660', label: 'SK하이닉스' }, { kind: 'narrative', ref: 'HBM', label: 'HBM' }] })
  post.mockRestore()
})
