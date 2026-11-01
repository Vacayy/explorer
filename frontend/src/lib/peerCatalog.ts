import { z } from 'zod'
import type { PeerCatalog } from '@/types/peer'

const text = z.string().trim().min(1)
const date = z.iso.date()
const source = z.object({
  url: z.url().refine(value => ['https:', 'http:'].includes(new URL(value).protocol), '공개 웹 근거만 허용합니다'),
  claim: text,
  verification: text,
  period: text.optional(),
  publishedAt: date.optional(),
})
const schema = z.object({
  version: text,
  asOf: date,
  groups: z.array(z.object({ id: text, name: text, scope: z.enum(['product', 'value_chain']), interpretation: text })),
  companies: z.array(z.object({
    code: z.string().regex(/^\d{6}$/), name: text, asOf: date,
    aliases: z.array(text), products: z.array(text).min(1), groupIds: z.array(text).min(1),
    caveats: z.array(text), sources: z.array(source).min(1),
  })),
}).superRefine((catalog, ctx) => {
  const ids = new Set<string>()
  for (const group of catalog.groups) {
    if (ids.has(group.id)) ctx.addIssue({ code: 'custom', message: `중복 그룹: ${group.id}` })
    ids.add(group.id)
  }
  const codes = new Set<string>()
  for (const company of catalog.companies) {
    if (codes.has(company.code)) ctx.addIssue({ code: 'custom', message: `중복 종목: ${company.code}` })
    codes.add(company.code)
    if (company.asOf > catalog.asOf) ctx.addIssue({ code: 'custom', message: '카탈로그 이후의 조사일' })
    if (new Set(company.groupIds).size !== company.groupIds.length) ctx.addIssue({ code: 'custom', message: `중복 소속: ${company.code}` })
    for (const id of company.groupIds) if (!ids.has(id)) ctx.addIssue({ code: 'custom', message: `없는 그룹 참조: ${id}` })
  }
})

export function parsePeerCatalog(input: unknown): PeerCatalog {
  return schema.parse(input)
}

export function selectPeerCompanies(catalog: PeerCatalog, groupId: string, query: string) {
  const needle = query.trim().toLocaleLowerCase('ko-KR')
  return catalog.companies.filter(company =>
    (!groupId || company.groupIds.includes(groupId)) &&
    (!needle || [company.name, company.code, ...company.aliases, ...company.products].join(' ').toLocaleLowerCase('ko-KR').includes(needle)),
  )
}
