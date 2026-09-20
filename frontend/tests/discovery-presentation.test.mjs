import { test } from 'node:test'
import assert from 'node:assert/strict'
import { safeEvidenceUrl, timePrecision, claimKind, discoveryPriceAdjustment } from '../src/components/company/discoveryPresentation.ts'

test('stored citations cannot open script, local file, or malformed URLs', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,<script>bad</script>', 'file:///etc/passwd', '//example.com', 'not a URL', null]) assert.equal(safeEvidenceUrl(url), null)
  assert.equal(safeEvidenceUrl('https://example.com/source?id=4'), 'https://example.com/source?id=4')
})

test('research labels keep source claims, model inference, and unknown time separate', () => {
  assert.equal(claimKind('source_claim'), '자료 작성자의 주장')
  assert.equal(claimKind('inference'), '모델의 추론')
  assert.equal(timePrecision('unknown'), '공개 시점 미확인')
  assert.equal(timePrecision('new-provider-format'), '자료의 공개 시점 확인 필요')
  assert.equal(discoveryPriceAdjustment({ checks: { price_adjustment: { source_status: 'adjusted' } } }), 'adjusted')
  assert.equal(discoveryPriceAdjustment(null), undefined)
})
