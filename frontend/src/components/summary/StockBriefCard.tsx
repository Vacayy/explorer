import { useState } from "react"
import { ChevronDown, Loader2, Scale, TrendingDown, TrendingUp, Minus } from "lucide-react"
import { Markdown } from "@/components/shared/Markdown"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import api from "@/api/client"
import { stockBriefQuery, stockBriefComputeQuery, stockBriefHistoryQuery } from "@/api/spine"
import { ProposalPanel } from "@/components/shared/ProposalPanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Expandable } from "@/components/shared/Expandable"

/**
 * 종목 AI 브리프 — 도시에 첫 화면 (P2-1, product-v3.md §3).
 * "지금 이 종목에서 알아야 할 것": 다이제스트·신호·일정·내 논지를 종합.
 * 게으른 생성: 입력이 바뀐 경우에만 LLM (stale → compute 쿼리 자동 발화, 종목별 키잉).
 */
export default function StockBriefCard({ stockCode }: { stockCode: string }) {
  const { data } = useQuery(stockBriefQuery(stockCode))
  const compute = useQuery(stockBriefComputeQuery(stockCode, !!data?.stale))

  const b = compute.data ?? data
  // 재료 자체가 없으면(수집 언급·신호 0) 카드 생략 — 도시에를 비AI 데이터로만
  if (!b || (b.status === "empty" && !b.stale && !compute.isFetching)) return null

  return (
    <ProposalPanel
      title="AI 브리프 — 지금 알아야 할 것"
      subtitle={b.created_at ? `${b.created_at.slice(0, 16).replace("T", " ")} 기준` : undefined}
      maxHeight="70vh"
      className="bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))]"
      contentClassName="space-y-3"
    >
      {compute.isFetching && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            새 재료를 반영해 브리프 생성 중… (수십 초 걸릴 수 있습니다)
          </div>
        )}
        {b.revision_call && (
          <div className="flex gap-2 rounded-md bg-card/60 border px-3 py-2">
            {b.revision_call.direction === "up" ? <TrendingUp className="h-3.5 w-3.5 text-up shrink-0 mt-0.5" />
              : b.revision_call.direction === "down" ? <TrendingDown className="h-3.5 w-3.5 text-down shrink-0 mt-0.5" />
              : <Minus className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />}
            <p className="text-xs">
              <span className={`font-semibold ${b.revision_call.direction === "up" ? "text-up" : b.revision_call.direction === "down" ? "text-down" : "text-muted-foreground"}`}>
                추정치 방향 콜 — {b.revision_call.direction === "up" ? "상향 우세" : b.revision_call.direction === "down" ? "하향 우세" : "유지"}
              </span>{" "}
              {b.revision_call.rationale}
              <span className="block text-[10px] text-muted-foreground mt-0.5">
                시장 컨센서스(애널리스트 추정치)가 앞으로 움직일 방향에 대한 AI 가설 — 기록되어 실제 변화와 대조됩니다
              </span>
            </p>
          </div>
        )}
        {data?.has_thesis === false && <ThesisPrompt stockCode={stockCode} />}
        {data?.thesis && <ThesisView stockCode={stockCode} thesis={data.thesis} />}
        {b.thesis_check && (
          <div className="flex gap-2 rounded-md bg-hypothesis/10 border border-hypothesis/30 px-3 py-2">
            <Scale className="h-3.5 w-3.5 text-hypothesis shrink-0 mt-0.5" />
            <p className="text-xs">
              <span className="font-semibold text-hypothesis">내 논지 점검</span> {b.thesis_check}
              <span className="block text-[10px] text-muted-foreground mt-0.5">
                팔로우에 등록한 나의 투자 논지를 새 증거가 지지/반박하는지 — 위 콜(시장 기대)과 달리 대상은 '내 가설'
              </span>
            </p>
          </div>
        )}
        {/* 근거 재료 — 이 브리프는 무엇을 보고 썼나 (언급 없이 공시만으로 쓰일 수도 있다) */}
        {(data?.evidence?.length ?? 0) > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] text-muted-foreground shrink-0">근거 재료</span>
            {data!.evidence!.map((e) => (
              <Badge key={e} variant="secondary" className="text-[10px] font-normal">{e}</Badge>
            ))}
          </div>
        )}
        {b.brief && (
          <>
            <Expandable collapsedHeight={300}>
              <Markdown className={compute.isFetching ? "opacity-60" : ""}>{b.brief}</Markdown>
            </Expandable>
            <div className="text-right">
              <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                AI 종합 · 열람 시점 갱신 — 검증 필요
              </Badge>
            </div>
            <BriefHistory stockCode={stockCode} />
          </>
        )}
        {!b.brief && !compute.isFetching && b.status === "unavailable" && (
          <p className="text-xs text-muted-foreground py-1">LLM 엔진이 연결되면 열람 시 자동 생성됩니다.</p>
        )}
        {!b.brief && !compute.isFetching && compute.isError && (
          <p className="text-xs text-muted-foreground py-1">브리프 생성에 실패했습니다. 다시 열람하면 재시도됩니다.</p>
        )}
    </ProposalPanel>
  )
}

/** 논지 원문 열람·수정 — 원문은 불변 저장, AI는 점검(thesis_check)만 생성 */
function ThesisView({ stockCode, thesis }: { stockCode: string; thesis: string }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(thesis)
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: async () =>
      (await api.post("/api/watchlist", { stock_code: stockCode, thesis: text.trim() })).data,
    onSuccess: () => {
      toast.success("논지 수정 — 다음 브리프에 반영됩니다")
      setEditing(false)
      qc.invalidateQueries({ queryKey: ["spine", "stock-brief", stockCode] })
      qc.invalidateQueries({ queryKey: ["watchlist"] })
    },
    onError: () => toast.error("수정 실패 — 잠시 후 다시 시도해주세요"),
  })

  return (
    <Collapsible>
      <div className="flex items-center gap-1.5">
        <CollapsibleTrigger className="group/th flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
          <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/th:rotate-180" />
          내 논지 원문 <span className="opacity-70">— 아래 점검의 기준. AI가 고쳐 쓰지 않습니다</span>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent>
        {editing ? (
          <div className="mt-1.5 space-y-2">
            <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} className="text-sm" />
            <div className="flex justify-end gap-2">
              <Button size="xs" variant="ghost" onClick={() => { setEditing(false); setText(thesis) }}>취소</Button>
              <Button size="xs" disabled={!text.trim() || save.isPending} onClick={() => save.mutate()}>
                {save.isPending ? "저장 중…" : "저장"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-1.5 rounded-md border px-3 py-2">
            <p className="text-xs whitespace-pre-wrap leading-relaxed">{thesis}</p>
            <div className="text-right mt-1">
              <Button size="xs" variant="ghost" className="text-[11px] text-muted-foreground"
                onClick={() => { setText(thesis); setEditing(true) }}>수정</Button>
            </div>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

/** 논지 미등록 시 등록 유도 — 논지가 있어야 '내 논지 점검'(내 가설 vs 새 증거)이 작동한다 */
function ThesisPrompt({ stockCode }: { stockCode: string }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: async () =>
      (await api.post("/api/watchlist", { stock_code: stockCode, thesis: text.trim() })).data,
    onSuccess: () => {
      toast.success("논지 등록 — 다음 브리프부터 새 증거가 이 논지를 지지/반박하는지 점검합니다")
      setOpen(false)
      qc.invalidateQueries({ queryKey: ["spine", "stock-brief", stockCode] })
      qc.invalidateQueries({ queryKey: ["watchlist"] })
    },
    onError: () => toast.error("등록 실패 — 잠시 후 다시 시도해주세요"),
  })

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30">
        <Scale className="h-3.5 w-3.5 shrink-0" />
        내 투자 논지가 없습니다 — 등록하면 새 증거가 논지를 지지/반박하는지 브리프가 점검합니다. 클릭해서 등록
      </button>
    )
  }
  return (
    <div className="rounded-md border border-dashed px-3 py-2 space-y-2">
      <p className="text-[11px] text-muted-foreground">
        이 종목에 대한 나의 투자 논지 — 예: "HBM 구조 전환으로 사이클주에서 성장주로 리레이팅될 것"
      </p>
      <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
        placeholder="한두 문장이면 충분합니다" className="text-sm" />
      <div className="flex justify-end gap-2">
        <Button size="xs" variant="ghost" onClick={() => setOpen(false)}>취소</Button>
        <Button size="xs" disabled={!text.trim() || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "저장 중…" : "논지 등록"}
        </Button>
      </div>
    </div>
  )
}

/** 지난 브리프 아카이브 — 펼칠 때만 조회 (append-only stock_briefs) */
function BriefHistory({ stockCode }: { stockCode: string }) {
  const [open, setOpen] = useState(false)
  const history = useQuery(stockBriefHistoryQuery(stockCode, open))
  return (
    <Collapsible className="border-t pt-2" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="group/bh flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
        <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]/bh:rotate-180" />
        지난 브리프
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-3 pt-2">
          {history.isLoading && <p className="text-[11px] text-muted-foreground">불러오는 중…</p>}
          {history.data?.length === 0 && (
            <p className="text-[11px] text-muted-foreground">이전 브리프가 없습니다 — 재료가 바뀔 때마다 새 판이 쌓입니다.</p>
          )}
          {history.data?.map((h) => (
            <div key={h.created_at} className="rounded-md border px-3 py-2">
              <div className="text-[11px] text-muted-foreground tabular-nums mb-1">
                {h.created_at.slice(0, 16).replace("T", " ")}
              </div>
              {h.thesis_check && <p className="text-[11px] text-hypothesis mb-1">⚖ {h.thesis_check}</p>}
              <Markdown className="text-xs">{h.brief ?? ""}</Markdown>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
