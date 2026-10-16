import { useNavigate } from "react-router-dom"
import { Crosshair, Search } from "lucide-react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { VerdictBadge } from "@/components/knowledge/QuestionsSection"
import { NODE_LABEL } from "@/components/explore/graph/types"
import { useNarrativeCheckpoint, useNarrativeTopics } from "@/hooks/useWorld"
import type { WorldCheckpoint } from "@/types"

const KIND_LABEL: Record<string, string> = { portfolio: "보유", watch: "관심" }

/** 종목 발견(CodeAct) 자연어 입력 초안 — 실행은 사용자가 누를 때만 */
export function discoverPrefill(cp: WorldCheckpoint): string | null {
  const b = cp.beneficiaries ?? []
  const groups = b.filter(x => x.type !== "company").map(x => x.name)
  const stocks = b.filter(x => x.type === "company").map(x => x.name)
  if (!groups.length && !stocks.length) return null
  const lines = ["다음 조건을 모두 만족하는 종목을 찾아줘.", `- '${cp.title ?? cp.topic}' 서사의 수혜 후보`]
  if (groups.length) lines.push(`- 섹터·테마: ${groups.join(", ")}`)
  if (stocks.length) lines.push(`- 함께 볼 종목: ${stocks.join(", ")}`)
  return lines.join("\n")
}

/**
 * 서사 상세 상단 체크포인트 — 핵심질문(추적 중이면 질문 허브로) · 흔들릴 조건 · 수혜 섹터·종목 · 걸린 내 종목.
 * 전부 저장분 조회(GET /api/spine/world/checkpoint). 읽을 것이 하나도 없으면 카드를 숨긴다.
 */
export function NarrativeCheckpoint({ topic }: { topic: string }) {
  const q = useNarrativeCheckpoint(topic)
  const { topics } = useNarrativeTopics()
  const navigate = useNavigate()
  if (q.isLoading) return <Skeleton className="mb-4 h-24 w-full rounded-xl" />
  // 오류여도 본문 읽기는 막지 않는다 — 카드만 조용히 생략(서사 본문이 1차 정보)
  if (q.isError || !q.data || q.data.status !== "ok") return null
  const cp = q.data
  const falsifiers = cp.falsifiers ?? [], beneficiaries = cp.beneficiaries ?? [], mine = cp.my_stocks ?? []
  if (!cp.core_question && !falsifiers.length && !beneficiaries.length && !mine.length) return null
  const prefill = discoverPrefill(cp)
  const tracked = cp.question?.status === "tracking"

  return <Card className="mb-4 border-l-2 border-l-primary">
    <CardContent className="space-y-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Crosshair aria-hidden="true" className="size-4 text-primary" />
        <h2 className="text-sm font-semibold">체크포인트</h2>
        <span className="text-[11px] text-muted-foreground">이 서사를 판단으로 옮길 때 볼 것</span>
        <Button variant="outline" size="sm" className="ml-auto h-7" disabled={!prefill}
          title={prefill ? "수혜 후보를 조건으로 종목 발견 입력창에 채웁니다(실행은 직접)" : "수혜 후보가 없습니다"}
          onClick={() => prefill && navigate(`/discover?intent=natural&q=${encodeURIComponent(prefill)}`)}>
          <Search aria-hidden="true" />종목 발견에서 보기
        </Button>
      </div>

      {cp.core_question && <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground">핵심질문</p>
        {cp.question && tracked
          ? <Link to={`/question/${cp.question.id}`} className="flex flex-wrap items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-sm hover:border-primary">
              <span className="min-w-0 flex-1">{cp.core_question}</span>
              <VerdictBadge v={cp.question.confirm_verdict} prefix="확정 " />
              <VerdictBadge v={cp.question.lead_verdict} prefix="선행 " />
            </Link>
          : <p className="flex flex-wrap items-center gap-1.5 text-sm">
              <span>{cp.core_question}</span>
              <Badge variant="outline" className="text-[10px] text-muted-foreground">{cp.question?.status === "proposed" ? "질문 제안 대기" : "추적 안 함"}</Badge>
            </p>}
      </div>}

      {falsifiers.length > 0 && <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground">흔들릴 조건</p>
        <ul className="list-disc space-y-0.5 pl-4 text-sm">
          {falsifiers.map(f => <li key={f.condition} title={f.about ?? undefined}>{f.condition}</li>)}
        </ul>
      </div>}

      {beneficiaries.length > 0 && <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground">수혜 섹터·종목</p>
        <div className="flex flex-wrap gap-1.5">
          {beneficiaries.map(b => {
            const label = <><span className="text-[9px] text-muted-foreground">{NODE_LABEL[b.type] ?? b.type}</span>{b.name}</>
            const cls = "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs"
            if (b.stock_code) return <Link key={b.name} to={`/analyze/${b.stock_code}/summary`} className={`${cls} hover:border-primary`}>{label}</Link>
            if (topics.has(b.name)) return <Link key={b.name} to={`/narrative?topic=${encodeURIComponent(b.name)}`} className={`${cls} hover:border-primary`}>{label}</Link>
            return <span key={b.name} className={cls}>{label}</span>
          })}
        </div>
      </div>}

      {mine.length > 0 && <div className="flex flex-wrap items-center gap-1.5">
        <p className="text-[11px] text-muted-foreground">내 종목</p>
        {mine.map(s => <Badge key={s.stock_code} asChild variant="secondary" className="text-[11px]">
          <Link to={`/analyze/${s.stock_code}/summary`}>{s.name ?? s.stock_code}<span className="text-muted-foreground">· {s.kinds.map(k => KIND_LABEL[k] ?? k).join("·")}</span></Link>
        </Badge>)}
      </div>}
    </CardContent>
  </Card>
}
