// Session CSRF is held only in memory and replaced on each session check.
let token: string | null = null

export function setMemberCsrf(value: string | null) { token = value }
export function getMemberCsrf() { return token }
