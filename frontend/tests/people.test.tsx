import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '../src/components/ui/tooltip'
import { personPath, roleFilter, verdictSummary } from '@/lib/person'
import type { PeopleHome, PeopleHomeRow, PersonDetail } from '../src/types'

describe('인물 공용 규칙 (ia-redesign §4.23)', () => {
  it('id 주소 · 역할 필터 · 판정 분포(0은 뺀다)', () => {
    expect(personPath(5215)).toBe('/person/5215')
    expect(roleFilter('guru')).toBe('guru')
    expect(roleFilter('analyst')).toBe('all')
    expect(roleFilter(null)).toBe('all')
    expect(verdictSummary(['supports', 'untestable', 'nodata', 'nodata'])).toBe('지지 1 · 반증 불가 1 · 데이터 없음 2')
  })
})

const row = (id: number, name: string, role: PeopleHomeRow['role'], extra: Partial<PeopleHomeRow> = {}): PeopleHomeRow => ({
  entity_id: id, name, role, doc_count: 10, mentions_7d: 5, delta_7d: 2, last_doc_title: '최근 글', last_doc_id: 1,
  last_doc_at: '2026-11-04T00:00:00', top_stocks: ['엔비디아'], following: true, records: 0, ...extra,
})
const exec = { role: 'executive' as const, org: 'NVIDIA', org_code: 'NVDA', title: 'CEO', source: 'transcript' }
const guru = { role: 'guru' as const, org: '오크트리 캐피털', org_code: null, title: null, source: 'memo' }
const HOME: PeopleHome = {
  summary: { followed: 1, followed_mentions_7d: 5, recorded_people: 2, premises: 8, mentioned: 4197, mentioned_2plus: 1059 },
  role_counts: { all: 3, policy: 0, executive: 1, guru: 1 },
  followed: [row(4261, '젠슨 황', exec)],
  recorded: [
    { entity_id: 5215, name: '하워드 막스', role: guru, doc_count: 21, premises: [{ key: 'low_rate_over', claim: '초저금리 시대는 끝났다', status: 'supports' }] },
    { entity_id: null, name: '래리 서머스', role: null, doc_count: 0, premises: [{ key: 'low_rate_over', claim: '초저금리 시대는 끝났다', status: 'supports' }] },
  ],
  recorded_status: 'ok',
  rising: [row(4704, '빌 애크먼', null, { following: false })],
  as_of: null,
}
const state: { home: () => unknown; detail: () => unknown; resolve: () => unknown } = {
  home: () => ({ isPending: false, isError: false, data: HOME }),
  detail: () => ({ isPending: true }),
  resolve: () => ({ isPending: true }),
}
vi.mock('@/hooks/usePeople', () => ({
  usePeopleHome: () => state.home(),
  usePersonDetail: () => state.detail(),
  usePersonResolve: () => state.resolve(),
  usePeopleDirectory: () => ({ isPending: true }),
}))
const { default: PeopleHomePage } = await import('../src/components/person/PeopleHomePage')
const { default: PersonDetailPage, PersonNameRedirect } = await import('../src/components/person/PersonDetailPage')

afterEach(cleanup)
function Where() { const l = useLocation(); return <output data-testid="where">{l.pathname + l.search}</output> }
const wrap = (path: string) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={[path]}>
  <Routes>
    <Route path="/people" element={<><PeopleHomePage /><Where /></>} />
    <Route path="/person" element={<><PersonNameRedirect /><Where /></>} />
    <Route path="/person/:id" element={<><PersonDetailPage /><Where /></>} />
  </Routes>
</MemoryRouter></TooltipProvider></QueryClientProvider>)

describe('인물 홈 /people (§4.23.4 A)', () => {
  it('요약 · 역할 칩 수 · 세 목록, 인물 엔티티가 없는 사람은 링크 없이 "인물 없음"', () => {
    wrap('/people')
    expect(screen.getByText('4,197명')).toBeTruthy()
    expect(screen.getByRole('radio', { name: '경영자 1' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '젠슨 황' }).getAttribute('href')).toBe('/person/4261')
    expect(screen.getByRole('link', { name: '하워드 막스' }).getAttribute('href')).toBe('/person/5215')
    expect(screen.queryByRole('link', { name: '래리 서머스' })).toBeNull()
    expect(screen.getByText(/인물 없음/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '팔로우' })).toBeTruthy()
  })
  it('역할 칩은 URL ?role=로 거른다', () => {
    wrap('/people')
    fireEvent.click(screen.getByRole('radio', { name: '구루 1' }))
    expect(screen.getByTestId('where').textContent).toBe('/people?role=guru')
    expect(screen.queryByRole('link', { name: '젠슨 황' })).toBeNull()
    expect(screen.getByRole('link', { name: '하워드 막스' })).toBeTruthy()
  })
  it('전제 원장 실패는 그 블록만 오류, 팔로우는 그대로', () => {
    state.home = () => ({ isPending: false, isError: false, data: { ...HOME, recorded: [], recorded_status: 'error' } })
    wrap('/people')
    expect(screen.getByText('전제 원장을 불러오지 못했습니다.')).toBeTruthy()
    expect(screen.getByRole('link', { name: '젠슨 황' })).toBeTruthy()
    state.home = () => ({ isPending: false, isError: false, data: HOME })
  })
})

const DETAIL: PersonDetail = {
  entity_id: 5215, requested_id: 13605, name: '하워드 막스', role: guru,
  merged_names: [{ entity_id: 13605, name: '호워드 막스', type: 'person', docs: 1, rule: 'spelling' }], following: false,
  mentions: { count: 21, first_at: '2021-07-29', last_at: '2026-10-24' },
  own_docs: [{ id: 1, title: 'Sea Change', published_at: '2022-12-13', source_type: 'memo' }], own_total: 35, own_source: '오크트리 캐피털',
  cited: [{ id: 2, title: '인용 글', published_at: '2026-10-24', source_type: 'telegram' }], cited_total: 8,
  flow: [{ year: '2022', own: 8, cited: 3 }],
  premises: [{ key: 'low_rate_over', claim: '초저금리 시대는 끝났다', status: 'supports', kind: '공유', evidence: ['10년 금리 4.91%'], rule: '규칙', sources: [], said_at: '2022-12-13',
    co_holders: [{ label: 'BIS', kind: 'org', entity_id: null, name: null }, { label: 'El-Erian', kind: 'person', entity_id: 5049, name: 'Mohamed El-Erian' }] }],
  premises_status: 'ok', co_entities: [], relations: [], profile: null, profile_stale: true, new_since_profile: null,
}

describe('인물 상세 /person/:id (§4.23.4 B) · 옛 이름 주소(§10.6)', () => {
  it('묶인 이름 id로 오면 대표 주소로 바꾸고, 묶은 이름 한 줄과 기록 원장을 보인다', () => {
    state.detail = () => ({ isPending: false, isError: false, data: DETAIL })
    wrap('/person/13605')
    expect(screen.getByTestId('where').textContent).toBe('/person/5215')
    expect(screen.getByText('같은 사람으로 묶은 이름: 호워드 막스')).toBeTruthy()
    expect(screen.getAllByText('초저금리 시대는 끝났다').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: 'Mohamed El-Erian' })[0].getAttribute('href')).toBe('/person/5049')
    expect(screen.getByRole('button', { name: '프로필 만들기' })).toBeTruthy()   // 열람으로는 만들지 않는다
    expect(screen.queryByText('다른 사람인가요?')).toBeNull()                     // 사용자에게 이름 정리를 넘기지 않는다
  })
  it('/person?name= → 서버가 찾은 대표 id로, 못 찾으면 빈 상태', () => {
    state.resolve = () => ({ isPending: false, isError: false, data: { entity_id: 5215, name: '하워드 막스' } })
    wrap('/person?name=호워드 막스')
    expect(screen.getByTestId('where').textContent).toBe('/person/5215')
    cleanup()
    state.resolve = () => ({ isPending: false, isError: false, data: { entity_id: null, name: null } })
    wrap('/person?name=없는사람')
    expect(screen.getByText("'없는사람'(이)라는 인물을 찾지 못했습니다.")).toBeTruthy()
  })
})
