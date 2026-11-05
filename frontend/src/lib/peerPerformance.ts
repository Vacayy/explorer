import { z } from 'zod'
import type { PeerPriceSnapshot } from '@/types/peer'

const schema = z.object({
  version: z.string().min(1), asOf: z.iso.date(), collectedAt: z.iso.datetime({ offset: true }),
  sourceUrl: z.url().refine(url => new URL(url).protocol === 'https:'),
  sourceHash: z.string().regex(/^[a-f0-9]{64}$/),
  field: z.literal('regularMarketClosingPrice'), session: z.literal('KRX_REGULAR'),
  adjustmentStatus: z.literal('unverified'),
  dates: z.array(z.iso.date()).min(1),
  prices: z.record(z.string().regex(/^\d{6}$/), z.array(z.number().positive().nullable())),
  qualityIssues: z.array(z.object({ code: z.string().regex(/^\d{6}$/), date: z.iso.date(), reason: z.string().min(1), sourceUrl: z.url() })),
  caveats: z.array(z.string()),
}).superRefine((snapshot, context) => {
  if (snapshot.dates.at(-1) !== snapshot.asOf) context.addIssue({ code: 'custom', message: '기준일과 마지막 관측일 불일치' })
  if (snapshot.dates.some((date, index) => index > 0 && date <= snapshot.dates[index - 1])) context.addIssue({ code: 'custom', message: '일자 중복 또는 정렬 오류' })
  for (const [code, prices] of Object.entries(snapshot.prices)) {
    if (prices.length !== snapshot.dates.length) context.addIssue({ code: 'custom', message: `${code} 관측 길이 불일치` })
  }
})
export function parsePeerPrices(input: unknown): PeerPriceSnapshot { return schema.parse(input) }

export function normalizedPeerPath(snapshot: PeerPriceSnapshot, code: string, days: number): number[] | null {
  if (![5, 20, 60].includes(days) || snapshot.dates.length < days + 1) return null
  const start = snapshot.dates[snapshot.dates.length - days - 1]
  if (snapshot.qualityIssues.some(issue => issue.code === code && issue.date > start && issue.date <= snapshot.asOf)) return null
  const series = snapshot.prices[code]?.slice(-days - 1)
  if (!series || series.length !== days + 1 || series.some(value => value === null || !Number.isFinite(value) || value <= 0)) return null
  const valid = series as number[]
  return valid.map(value => value / valid[0] * 100)
}
