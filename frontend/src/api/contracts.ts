import { validateOpenApiResponse } from './openapi.ts'
import { z } from 'zod'
import { ApiError } from './errors.ts'

// Keep unknown fields for forward compatibility; never coerce malformed values to empty data.
const text = z.string()
const nullableText = text.nullable()
const number = z.number()
const id = z.number().int()
const object = z.looseObject
export const companySchema = object({ corp_code: text, corp_name: text, stock_code: nullableText, market: nullableText, sector: nullableText })
export const boardSchema = object({
  id, label: text, sort: number, updated_at: text,
  items: z.array(object({ i: text, widget: text, x: number, y: number, w: number.positive(), h: number.positive(), params: z.record(text, z.unknown()).optional() })),
})
const entitySchema = object({ entity_id: id, type: text, name: text, aliases: nullableText, link_type: text, confidence: number.nullable() })
export const feedSchema = object({
  items: z.array(object({
    id, source_type: text, title: text, url: text, published_at: text,
    summary: nullableText, channel: nullableText, channel_kind: nullableText, channel_key: nullableText,
    content: nullableText, images: z.array(text), enrich_model: nullableText, entities: z.array(entitySchema),
    digest_status: nullableText.optional(), digest_error: nullableText.optional(), video_digest: nullableText.optional(), transcript: nullableText.optional(),
  })),
  total: id.nonnegative(), page: id.positive(), size: id.positive(), as_of: text,
})
export const indicesSchema = object({
  as_of: nullableText, degraded: z.array(text), any_open: z.boolean(),
  items: z.array(object({ key: text, label: text, region: text, is_open: z.boolean(), price: number.nullable(), change_pct: number.nullable(), spark: z.array(number), as_of: nullableText })),
})
const recentCallSchema = object({ transcript_id: id, ticker: text, company_name: nullableText, fiscal_year: id, fiscal_period: text,
  cy: nullableText, call_date: nullableText, provider: nullableText, fetched_at: nullableText, has_digest: z.boolean() })
const transcriptFollowSchema = object({ ticker: text, company_name: text, next_report_date: nullableText.optional(), calendar_checked_at: nullableText.optional(), latest: object({ transcript_id: id }).nullable() })

/** This operation has two response shapes selected by a query parameter. */
export const collectPlanSchema = object({
  dry_run: z.literal(true), budget: id.nonnegative(), would_request: id.nonnegative(),
  skipped_cache: id.nonnegative(), planned: z.array(text), over_budget: id.nonnegative(),
})
const collectStartedSchema = object({ started: z.literal(true), budget: id.nonnegative() })

/** Route contracts apply equally to direct Axios calls and query factories. Add specific routes before parameter routes. */
export const responseContracts: { method: string; path: RegExp; schema: z.ZodType }[] = [
  { method: 'get', path: /^\/api\/companies\/search$/, schema: z.array(companySchema) },
  { method: 'get', path: /^\/api\/companies\/[^/]+$/, schema: companySchema },
  { method: 'get', path: /^\/api\/dashboard\/boards$/, schema: z.array(boardSchema) },
  { method: 'post', path: /^\/api\/dashboard\/boards$/, schema: boardSchema },
  { method: 'put', path: /^\/api\/dashboard\/boards\/order$/, schema: z.array(boardSchema) },
  { method: 'patch', path: /^\/api\/dashboard\/boards\/\d+$/, schema: boardSchema },
  { method: 'get', path: /^\/api\/spine\/feed$/, schema: feedSchema },
  { method: 'get', path: /^\/api\/spine\/indices$/, schema: indicesSchema },
  { method: 'get', path: /^\/api\/spine\/transcript\/recent$/, schema: z.array(recentCallSchema) },
  { method: 'get', path: /^\/api\/spine\/transcript\/follow$/, schema: z.array(transcriptFollowSchema) },
]

export function parseResponse<T>(schema: { parse: (data: unknown) => T }, data: unknown): T {
  try { return schema.parse(data) } catch (cause) {
    throw new ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', undefined, {
      kind: 'schema', cause, issues: cause instanceof z.ZodError ? cause.issues : undefined,
    })
  }
}

export function validateResponse(method: string, url: string, data: unknown, status = 200) {
  const requestUrl = new URL(url, 'http://api.local')
  const path = requestUrl.pathname.replace(/\/$/, '')
  if (method.toLowerCase() === 'post' && path === '/api/spine/transcript/collect') {
    const preview = ['1', 'true'].includes(requestUrl.searchParams.get('dry_run')?.toLowerCase() ?? '')
    return preview ? parseResponse(collectPlanSchema, data) : parseResponse(collectStartedSchema, data)
  }
  const contract = responseContracts.find(c => c.method === method.toLowerCase() && c.path.test(path))
  return contract ? parseResponse(contract.schema, data) : validateOpenApiResponse(method, path, data, status)
}
