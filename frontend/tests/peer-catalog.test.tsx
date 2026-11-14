import prices from '@/data/peer-prices.json'
import { expect, it } from 'vitest'
import raw from '@/data/peer-catalog.json'
import { parsePeerCatalog } from '@/lib/peerCatalog'
import { locate } from '@/components/layout/navConfig'
import { companyEvidence, sourceCheck } from '@/lib/peerFrame'

it('validates the shipped evidence graph, rejects missing references and unsafe URLs', () => {
  const catalog = parsePeerCatalog(raw)
  expect(catalog.companies.length).toBeGreaterThanOrEqual(53)
  expect(catalog.companies.every(company => company.sources.length > 0)).toBe(true)
  const missing = structuredClone(raw); missing.companies[0].groupIds.push('absent')
  expect(() => parsePeerCatalog(missing)).toThrow('없는 그룹')
  const unsafe = structuredClone(raw); unsafe.companies[0].sources[0].url = 'javascript:alert(1)'
  expect(() => parsePeerCatalog(unsafe)).toThrow()
  const duplicate = structuredClone(raw); duplicate.companies.push(duplicate.companies[0])
  expect(() => parsePeerCatalog(duplicate)).toThrow('중복 종목')
})

it('robotics group (D-318) has six members whose link-only evidence is not counted as verified', () => {
  const catalog = parsePeerCatalog(raw)
  const members = catalog.companies.filter(c => c.groupIds.includes('robotics_automation'))
  expect(members.map(c => c.code).sort()).toEqual(['058610', '160190', '277810', '348340', '389500', '454910'])
  expect(members.every(c => companyEvidence(c).verified === 0)).toBe(true)
  expect(sourceCheck('link_only_not_compared: 링크만')).toBe('link')
  expect(sourceCheck('primary_search_snippet_only_open_502')).toBe('snippet')
  expect(sourceCheck('primary_original_verified')).toBe('original')
  expect(members.every(c => prices.prices[c.code as keyof typeof prices.prices]?.length === prices.dates.length)).toBe(true)
})

it('old peer routes sit under industry › 섹터 (Peer 그룹은 섹터 화면 탭, D-327)', () => {
  expect(locate('/discover/peers')).toEqual({ section: 'industry', tab: 'sectors' })
  expect(locate('/analyze/compare')).toEqual({ section: 'industry', tab: 'sectors' })
  expect(locate('/industry/반도체·전자부품')).toEqual({ section: 'industry', tab: 'sectors' })
})
