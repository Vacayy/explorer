/** 답변 생성 중인 대화 스레드 추적 — 전역 '답변 도착' 알림용 (sessionStorage). */
const KEY = "pending-answer-convs"

export function getPendingAnswers(): number[] {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? "[]")
  } catch {
    return []
  }
}

export function addPendingAnswer(id: number) {
  const ids = getPendingAnswers()
  if (!ids.includes(id)) sessionStorage.setItem(KEY, JSON.stringify([...ids, id]))
}

export function removePendingAnswer(id: number) {
  sessionStorage.setItem(KEY, JSON.stringify(getPendingAnswers().filter((x) => x !== id)))
}
