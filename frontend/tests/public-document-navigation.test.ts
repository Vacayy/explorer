import { expect, it } from 'vitest'
import { publicCompanyReturn, publicFeedReturn, publicFeedUrl } from '@/lib/publicDocumentNavigation'
it('round trips search, cursor and nested company filters', () => {
 const company = '/analyze/005930/summary?' + new URLSearchParams({price_range:'1y',sector:'반도체',sector_query:'?range=3m&map_query=%3Fv%3Dtable'})
 const feed = publicFeedUrl('삼성전자','opaque-next',company)
 expect(publicFeedReturn(feed)).toBe(feed)
 expect(new URLSearchParams(feed.split('?')[1]).get('company_return')).toBe(company)
})
it('rejects external, private, malformed and overlong return URLs', () => {
 for(const value of ['//evil.test/feed','https://evil.test/feed','/admin','/feed/saved','/feed#x','/feed\\evil','/feed?q='+'a'.repeat(121),'/feed?cursor=']) expect(publicFeedReturn(value)).toBe('/feed')
 for(const value of ['/analyze/005930/financials','//evil.test/analyze/005930/summary','/analyze/../admin','/analyze/005930/summary#x']) expect(publicCompanyReturn(value)).toBeNull()
 expect(publicFeedReturn('/feed?q=ok&company_return=%2Fadmin&unexpected=secret')).toBe('/feed?q=ok')
})

it('returns from approved document search to the US dossier and rejects other US routes', () => {
 const company = '/us/BRK-B?tab=evidence&months=12'
 const feed = publicFeedUrl('Berkshire', null, company)
 expect(publicFeedReturn(feed)).toBe(feed)
 expect(new URLSearchParams(feed.split('?')[1]).get('company_return')).toBe(company)
 for (const value of ['/us/MSFT/admin', '//evil.test/us/MSFT', '/us/../admin', '/us/%2Fadmin']) expect(publicCompanyReturn(value)).toBeNull()
})
