const mode = import.meta.env.VITE_ACCESS_MODE ?? 'private'
if (mode !== 'private' && mode !== 'public') throw new Error('Invalid VITE_ACCESS_MODE')
/** This is UI selection only. The server must independently enforce its mode. */
export const PUBLIC_ACCESS = mode === 'public'
