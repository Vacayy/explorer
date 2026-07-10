import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import ReactMarkdown from "react-markdown"
import { Sparkles, AlertTriangle } from "lucide-react"
import { askQuestion } from "@/api/spine"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { SourceBadge } from "@/components/shared/SourceBadge"

const GAP_LABEL: Record<string, string> = {
  unsupported: "근거 부족",
  contradiction: "모순",
  stale: "오래된 정보",
  missing: "빠진 정보",
}

const EXAMPLES = [
  "최근 SK하이닉스 관련 주요 이슈를 정리해줘",
  "메모리 반도체 사이클에 대한 시장 시각은?",
  "내 가설과 상충하는 최근 언급이 있어?",
]

/**
 * /ask — RAG 질의응답 (docs/specs/phase2-rag.md)
 * 규율: 답변은 수집 문서 근거 + 출처 인용. 답변 자체가 '가설'(모델 표시).
 * 갭 분석(근거 부족·모순·오래된 정보)을 일급 출력으로 노출.
 */
export default function AskPage() {
  const [question, setQuestion] = useState("")
  const ask = useMutation({ mutationFn: askQuestion })

  const submit = () => {
    if (question.trim() && !ask.isPending) ask.mutate(question.trim())
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <h2 className="text-xl font-bold">AI 질문</h2>
      <p className="text-xs text-muted-foreground">
        수집된 문서(텔레그램·블로그·내 가설 노트)를 근거로 답합니다. 근거 없는 내용은 답하지 않고, 갭(근거 부족·모순·오래된 정보)을 함께 표시합니다.
      </p>

      <div className="space-y-2">
        <Textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit() }}
          placeholder="예: 최근 SK하이닉스 수급 관련 언급을 정리해줘"
          rows={3}
        />
        <div className="flex items-center gap-2">
          <Button onClick={submit} disabled={ask.isPending || !question.trim()}>
            <Sparkles className="h-4 w-4" /> {ask.isPending ? "답변 생성 중… (~30초)" : "질문하기"}
          </Button>
          {!ask.data && !ask.isPending && (
            <div className="flex gap-1.5 flex-wrap">
              {EXAMPLES.map((ex) => (
                <button key={ex} onClick={() => setQuestion(ex)}
                  className="text-[11px] text-muted-foreground hover:text-foreground border rounded-full px-2 py-0.5">
                  {ex}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {ask.isPending && (
        <Card><CardContent className="py-5 space-y-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <p className="text-[11px] text-muted-foreground pt-1">검색 → 근거 문서 취합 → 종합 답변 생성 중…</p>
        </CardContent></Card>
      )}

      {ask.isError && <ErrorState message="답변 생성에 실패했습니다." onRetry={submit} />}

      {ask.data && !ask.isPending && (
        <div className="space-y-3">
          {/* 답변 — epistemic: 가설 스타일 (모델 표시) */}
          <Card className="border-l-2 border-l-hypothesis">
            <CardHeader className="pb-1 flex-row items-center gap-2">
              <CardTitle className="text-sm">답변</CardTitle>
              <Badge variant="outline" className="text-[10px] font-normal text-hypothesis border-hypothesis/40">
                AI 종합 · {ask.data.model}
              </Badge>
            </CardHeader>
            <CardContent className="prose prose-sm dark:prose-invert max-w-none text-sm
              [&_h2]:text-base [&_h2]:mt-3 [&_ul]:my-1 [&_li]:my-0.5">
              {ask.data.answer
                ? <ReactMarkdown>{ask.data.answer}</ReactMarkdown>
                : <p className="text-muted-foreground">관련 문서가 없어 답할 수 없습니다.</p>}
            </CardContent>
          </Card>

          {/* 갭 분석 — 일급 출력 */}
          {ask.data.gaps.length > 0 && (
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 text-hypothesis" /> 갭 분석
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1">
                  {ask.data.gaps.map((g, i) => (
                    <li key={i} className="text-xs flex gap-2">
                      <Badge variant="secondary" className="text-[10px] shrink-0">{GAP_LABEL[g.type] ?? g.type}</Badge>
                      <span className="text-muted-foreground">{g.note}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {/* 출처 */}
          {ask.data.citations.length > 0 && (
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-sm">출처 {ask.data.citations.length}건</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-1">
                  {ask.data.citations.map((c) => (
                    <li key={c.n} className="text-xs flex items-center gap-2">
                      <span className="text-muted-foreground tabular-nums shrink-0">[{c.n}]</span>
                      <SourceBadge sourceType={c.source_type} />
                      <Link to={`/doc/${c.doc_id}`} className="truncate hover:underline">{c.title}</Link>
                      <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">{(c.published_at || "").slice(0, 10)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}
