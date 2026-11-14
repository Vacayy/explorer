import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { splitSections } from '../src/components/chat/AssistantMessage'
import { DetailLayout } from '../src/components/shared/DetailLayout'
import { OPEN_AI_EVENT, openAi } from '../src/lib/aiPanel'

// 모바일 정리(ia-redesign §4.32) — 대화 답변 절 접기, 상세 화면 행동 바, AI 시트 열기
afterEach(() => cleanup())

it('folds an answer into lead + ## sections, ignoring ## inside code fences', () => {
  const md = '**결론:** 요약[1]\n\n## 1. 주가 흐름\n본문 A\n```\n## 코드 안\n```\n## **2. 실적**\n본문 B'
  const p = splitSections(md)!
  expect(p.lead).toBe('**결론:** 요약[1]')
  expect(p.sections.map(s => s.title)).toEqual(['1. 주가 흐름', '2. 실적'])
  expect(p.sections[0].body).toContain('## 코드 안')
})

it('keeps a short answer whole (fewer than two sections)', () => {
  expect(splitSections('짧은 답\n\n## 하나뿐\n본문')).toBeNull()
  expect(splitSections('제목 없는 답')).toBeNull()
})

it('detail layout: phone top bar and fixed action bar are separate from desktop actions', () => {
  render(<MemoryRouter><DetailLayout title="문서" backLabel="출처로 돌아가기" mobileBackLabel="출처로"
    actions={<button>데스크톱 동작</button>} mobileTop={<a href="https://example.com">원문 사이트</a>}
    mobileBar={<button>이 자료로 대화</button>}>본문</DetailLayout></MemoryRouter>)
  expect(screen.getByText('데스크톱 동작').parentElement!.className).toContain('max-md:hidden')
  expect(screen.getByText('원문 사이트').parentElement!.className).toContain('md:hidden')
  const bar = screen.getByText('이 자료로 대화').parentElement!
  expect(bar.className).toContain('fixed')
  expect(bar.className).toContain('md:hidden')
  expect(screen.getByText('출처로').className).toContain('md:hidden')
})

it('openAi opens the panel without sending a question', () => {
  const fn = vi.fn()
  window.addEventListener(OPEN_AI_EVENT, fn)
  const btn = document.createElement('button'); btn.onclick = openAi; document.body.append(btn)
  fireEvent.click(btn)
  expect(fn).toHaveBeenCalledTimes(1)
  window.removeEventListener(OPEN_AI_EVENT, fn); btn.remove()
})
