import { type ClassValue, clsx } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// 프로젝트 글자 크기 토큰(index.css --text-*)을 글자 크기로 등록 — 미등록이면 글자색으로 오인해 같은 요소의 text-ink 등을 지운다
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ["page", "section", "card-title", "reading", "caption", "weather"] } },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
