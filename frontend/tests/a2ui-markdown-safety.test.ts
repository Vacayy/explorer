import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@a2ui/markdown-it'

describe('A2UI markdown after sanitizer dependency update', () => {
  it('preserves readable formatting and safe links', async () => {
    const html = await renderMarkdown('**Evidence** [source](https://example.com/report)')
    const node = document.createElement('div')
    node.innerHTML = html
    expect(node.querySelector('strong')?.textContent).toBe('Evidence')
    expect(node.querySelector('a')?.getAttribute('href')).toBe('https://example.com/report')
  })

  it('does not create executable markup from untrusted markdown', async () => {
    const html = await renderMarkdown('<img src=x onerror="alert(1)"><script>alert(1)</script> [bad](javascript:alert(1))')
    const node = document.createElement('div')
    node.innerHTML = html
    expect(node.querySelector('script,[onerror],[onload]')).toBeNull()
    expect([...node.querySelectorAll('a')].some(a => a.href.startsWith('javascript:'))).toBe(false)
  })
})
