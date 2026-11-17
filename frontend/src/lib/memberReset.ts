/** Clear only application personal state; retain unrelated storage and theme. */
export function clearMemberBrowserState() {
  for (const name of ['localStorage', 'sessionStorage'] as const) {
    try {
      const storage = window[name]
      const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i))
      for (const key of keys) {
        if (key && (key.startsWith('explorer.') || key.startsWith('explorer:')
          || key.startsWith('project-tabs-') || key.startsWith('project-note-draft-')
          || key.startsWith('study-position-') || key === 'pending-answer-convs' || key === 'usage.session')) {
          storage.removeItem(key)
        }
      }
    } catch { /* Storage is unavailable; do not copy it elsewhere. */ }
  }
}

/** Full navigation discards component/module memory, attachments and old requests. */
export function leaveMemberSession() {
  window.location.replace('/home/kr')
}
