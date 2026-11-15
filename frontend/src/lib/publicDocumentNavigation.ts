// Return links accept only explicit public routes, never arbitrary navigation targets.
function localUrl(value: string | null): URL | null {
  if (!value || value.length > 8192 || !value.startsWith('/') || value.startsWith('//') || /[\u0000-\u0020\\#]/.test(value)) return null
  try { const url = new URL(value, 'https://local.invalid'); return url.origin === 'https://local.invalid' ? url : null } catch { return null }
}

export function publicCompanyReturn(value: string | null): string | null {
  const url = localUrl(value)
  return url && /^\/analyze\/\d{6}\/summary$/.test(url.pathname) ? url.pathname + url.search : null
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
  return publicFeedUrl(q, cursor, url.searchParams.get('company_return'))
}
