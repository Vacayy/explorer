/** Bounded, tab-local UI memory. Never stores source documents or generated content. */
export function sessionMemory<T>(key: string, limit = 100) {
  let values = new Map<string, T>()
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) || '[]')
    if (Array.isArray(stored)) values = new Map(stored.slice(-limit))
  } catch { /* unavailable or invalid storage */ }
  return {
    get: (id: string) => values.get(id),
    set: (id: string, value: T) => {
      values.delete(id); values.set(id, value)
      if (values.size > limit) values.delete(values.keys().next().value!)
      try { sessionStorage.setItem(key, JSON.stringify([...values])) } catch { /* private storage */ }
    },
  }
}
