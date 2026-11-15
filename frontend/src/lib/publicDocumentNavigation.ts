// Return links accept only explicit public routes, never arbitrary navigation targets.
function localUrl(value: string | null): URL | null {
  if (!value || value.length > 8192 || !value.startsWith('/') || value.startsWith('//') || /[\u0000-\u0020\\#]/.test(value)) return null
  try { const url = new URL(value, 'https://local.invalid'); return url.origin === 'https://local.invalid' ? url : null } catch { return null }
}

export function publicCompanyReturn(value: string | null): string | null {
  const url = localUrl(value)
  return url && (/^\/analyze\/\d{6}\/summary$/.test(url.pathname) || /^\/us\/[A-Za-z0-9][A-Za-z0-9.-]{0,19}$/.test(url.pathname)) ? url.pathname + url.search : null
}

export function publicFeedUrl(q: string, cursor: string | null = null, companyReturn: string | null = null): string {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  if (cursor !== null) params.set('cursor', cursor)
  const company = publicCompanyReturn(companyReturn)
  if (company) params.set('company_return', company)
  return `/feed${params.size ? `?${params}` : ''}`
}

export function publicFeedReturn(value: string | null): string {
  const url = localUrl(value)
  if (!url || url.pathname !== '/feed') return '/feed'
  const q = (url.searchParams.get('q') ?? '').trim()
  const cursor = url.searchParams.get('cursor')
  if (q.length > 120 || (cursor !== null && (!cursor || cursor.length > 2048))) return '/feed'
  const result = new URL(publicFeedUrl(q, cursor, url.searchParams.get('company_return')), 'https://local.invalid')
  for (const [key, limit] of Object.entries({ view: 16, channel: 2200, channel_type: 128, channel_q: 120, reader_topic: 120, reader_page: 3, reader_until: 64, reader_open: 1 })) {
    const value = url.searchParams.get(key)
    if (value && value.length <= limit) result.searchParams.set(key, value)
  }
  return result.pathname + result.search
}
