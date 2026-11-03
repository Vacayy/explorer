import { afterEach, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { DropletContent, DropletReveal, DropletTrigger } from '../src/components/shared/DropletReveal'

afterEach(() => cleanup())

it('opens the droplet content inside the panel and closes it again', () => {
  render(
    <DropletReveal>
      <p>요약</p>
      <DropletTrigger>브리핑 전체 보기</DropletTrigger>
      <DropletContent title="브리핑 전체" description="어젯밤 미국장"><p>본문 문단</p></DropletContent>
    </DropletReveal>,
  )
  const trigger = screen.getByRole('button', { name: '브리핑 전체 보기' })
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(screen.queryByText('본문 문단')).toBeNull()
  fireEvent.click(trigger)
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  expect(screen.getByText('본문 문단')).toBeTruthy()
  // 펼침 내용은 패널을 덮고(물방울 애니메이션) 패널 높이를 바꾸지 않는다
  const content = screen.getByText('본문 문단').closest('[data-slot=collapsible-content]')!
  expect(content.className).toContain('animate-droplet')
  expect(content.className).toContain('absolute')
  fireEvent.click(screen.getByRole('button', { name: '닫기' }))
  expect(screen.queryByText('본문 문단')).toBeNull()
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
})
