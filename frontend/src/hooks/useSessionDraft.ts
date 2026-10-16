import { useCallback, useRef, useState, type SetStateAction } from 'react'

/** Callers key the component when switching draft identity. Writes happen on edits, not on mount. */
export function useSessionDraft<T>(key: string, initial: T, validate: (value: unknown) => value is T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const saved: unknown = JSON.parse(sessionStorage.getItem(key) ?? 'null')
      return validate(saved) ? saved : initial
    } catch { return initial }
  })
  const current = useRef(value)
  const [stored, setStored] = useState<boolean | null>(null)
  const update = useCallback((next: SetStateAction<T>) => {
    const resolved = typeof next === 'function' ? (next as (value: T) => T)(current.current) : next
    current.current = resolved
    setValue(resolved)
    try { sessionStorage.setItem(key, JSON.stringify(resolved)); setStored(true) }
    catch { setStored(false) }
  }, [key])
  return [value, update, stored] as const
}
