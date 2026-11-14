import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { useCandidateAction, useNarrativeCandidates } from "@/hooks/useNarrativeLinks"
import { mdDate } from "@/lib/narrativeLinks"
import type { NarrativeCandidate } from "@/types"

const HOW = "Market Today에서 같은 태그로 이어진 화두가 2거래일 이상·3회차 이상 나왔는데 같은 이름의 서사가 없으면 후보로 올립니다. 하루 안에서만 3회차 나왔으면 관찰 중입니다. 승인하면 다음 내러티브 갱신 때 첫 버전을 만들고, 무시하면 14일 동안 다시 올리지 않습니다."
const FAILED = new Set(["empty", "not_found"])

function CandidateRow({ c }: { c: NarrativeCandidate }) {
  const act = useCandidateAction()
  const run = (action: "approve" | "dismiss") => act.mutate({ tag: c.tag, action }, {
    onSuccess: (r) => toast.success(action === "dismiss" ? `'${c.name}'을 14일 동안 후보에서 뺐습니다`
      : r.mode === "merge" ? `'${c.name}'을 '${r.narrative_topic}' 서사에 합쳤습니다` : `'${r.narrative_topic}' 서사를 다음 갱신 때 만듭니다`),
    onError: () => toast.error("처리하지 못했습니다. 다시 시도해 주세요"),
  })
  const tip = [
    c.linked.length > 0 ? `${c.linked.join("·")} 서사에 출처로만 걸려 있어요.` : "아직 어떤 서사에도 걸리지 않았어요.",
    c.merge_into ? `같은 기간에 생긴 '${c.merge_into.topic}' 서사(v${c.merge_into.version})와 출처 ${c.merge_into.overlap}건이 겹쳐요.` : null,
    c.status === "watching" ? "다른 거래일에 한 번 더 나오면 후보가 됩니다." : null,
  ].filter(Boolean).join(" ")
  return (
    <li className="space-y-2 py-3 first:pt-0 last:pb-0" data-candidate={c.status}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-sm font-semibold">{c.name}</span>
        <InfoTip label={`${c.name} 설명`}>{tip}</InfoTip>
        {c.status === "pending" && <Badge variant="outline" className="h-5 rounded-none border-hypothesis/40 px-1.5 text-[10px] font-normal text-hypothesis">후보</Badge>}
        {c.status === "watching" && <Badge variant="outline" className="h-5 rounded-none px-1.5 text-[10px] font-normal text-muted-foreground">관찰 중</Badge>}
        {c.status === "approved" && <Badge variant="outline" className="h-5 rounded-none px-1.5 text-[10px] font-normal">{FAILED.has(c.attempt ?? "") ? "재료 부족" : "다음 갱신 때 만듦"}</Badge>}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular-nums">{c.days}일 · {c.sessions}회차 · 출처 {c.sources}건</span>
      </div>
      <p className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] tabular-nums">
        {c.session_list.map((s) => <span key={s.mt_id} className="inline-flex items-center gap-1"><span aria-hidden="true" className="size-1.5 rounded-full bg-foreground" />{mdDate(s.trade_date)} {s.label}</span>)}
      </p>
      <ul className="space-y-0.5 text-sm text-muted-foreground">{c.titles.slice(0, 3).map((t) => <li key={t} className="truncate">{t}</li>)}</ul>
      {c.status === "pending" && <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={act.isPending} onClick={() => run("approve")}>{c.merge_into ? `'${c.merge_into.topic}'에 합치기` : "서사로 만들기"}</Button>
        <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => run("dismiss")}>무시</Button>
      </div>}
    </li>
  )
}

/**
 * Thesis › 지금 '내러티브 후보' (ia-redesign §9.2·§9.3) — Market Today에서 반복되는데 전용 서사가 없는 화두 묶음.
 * 후보는 [서사로 만들기]/[○○에 합치기]·[무시], 관찰 중은 표시만. 승인해도 바로 생성하지 않는다.
 */
export function NarrativeCandidatesCard() {
  const q = useNarrativeCandidates()
  const items = q.data?.items ?? []
  const pending = items.filter((c) => c.status === "pending").length
  return (
    <Card className="gap-0 py-0" aria-label="내러티브 후보" data-candidates>
      <header className="flex items-center gap-1 border-b px-4 py-3">
        <h2 className="text-section font-semibold">내러티브 후보</h2>
        <InfoTip label="후보는 어떻게 고르나요?">{HOW}</InfoTip>
        {pending > 0 && <Badge variant="secondary" className="ml-auto h-5 rounded-none px-1.5 font-mono text-[11px] font-normal">{pending}건</Badge>}
      </header>
      <div className="p-4">
        {q.isLoading ? <Skeleton className="h-32 w-full" />
          : q.isError ? <ErrorState message="내러티브 후보를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
          : items.length === 0 ? <p className="py-2 text-sm text-muted-foreground">반복되는 새 화두가 없어요.</p>
          : <ul className="divide-y">{items.map((c) => <CandidateRow key={c.tag} c={c} />)}</ul>}
      </div>
    </Card>
  )
}
