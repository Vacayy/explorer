import { Newspaper, Scale, TrendingUp, Waypoints } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"

/** 제안 카드 — 이 시스템의 도구 카탈로그(chat_tools 12종)가 잘 답하는 질문 유형 하나씩 */
const SUGGESTIONS: { icon: LucideIcon; title: string; q: string }[] = [
  { icon: Newspaper, title: "오늘의 이슈", q: "오늘 유입된 문서에서 주요 이슈를 정리해줘" },
  { icon: TrendingUp, title: "시세 흐름", q: "SK하이닉스 최근 2주 주가 흐름과 그 배경이 된 언급을 정리해줘" },
  { icon: Waypoints, title: "내러티브·인과", q: "메모리 반도체 사이클 내러티브의 현재 인과 구조와 최근 변화는?" },
  { icon: Scale, title: "가설 대질", q: "내 가설과 상충하는 최근 언급이 있어?" },
]

/**
 * 빈 상태 — 스레드가 선택되지 않았을 때. 인사 + 컴포저(children으로 중앙에 배치) + 제안 카드.
 * 질문 유형별 카드로 "무엇을 물을 수 있는가"를 보여준다(빈 프롬프트 마비 방지).
 */
export function ChatEmpty({ onPick, children }: { onPick: (q: string) => void; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex h-full w-full max-w-[768px] flex-col items-center justify-center gap-8 px-1 pb-10">
      <div className="text-center space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">무엇을 확인할까요?</h1>
        <p className="text-sm text-muted-foreground leading-relaxed">
          수집 문서·내러티브·인과 그래프·시세·시장 국면을 질문에 맞게 조회해 근거와 함께 답합니다.<br className="hidden sm:block" />
          근거 없는 내용은 답하지 않고, 갭(근거 부족·모순·오래된 정보)을 함께 표시합니다.
        </p>
      </div>

      <div className="w-full">{children}</div>

      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map(({ icon: Icon, title, q }) => (
          <Button key={title} variant="outline" onClick={() => onPick(q)}
            className="h-auto flex-col items-start gap-1 rounded-xl px-4 py-3 text-left font-normal whitespace-normal">
            <span className="flex items-center gap-1.5 text-[13px] font-medium">
              <Icon className="size-3.5 text-muted-foreground" /> {title}
            </span>
            <span className="text-xs leading-relaxed text-muted-foreground">{q}</span>
          </Button>
        ))}
      </div>
    </div>
  )
}
