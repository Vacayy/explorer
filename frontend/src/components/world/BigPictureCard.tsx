import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ChevronDown } from "lucide-react"
import { toast } from "sonner"
import api from "@/api/client"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { Markdown } from "@/components/shared/Markdown"
import { ContestedRow } from "@/components/world/ContestedPremises"
import type { NarrativeItem } from "@/components/explore/NarrativeList"
import { useBigPicture, useContestedPremises, useNarrativeIndex } from "@/hooks/useWorld"
import { ageDays, inputsLabel, kstDay, kstShort, staleLevel } from "@/lib/bigPicture"
import { cn } from "@/lib/utils"
import type { WorldBigPicture, WorldMega } from "@/types"

const HOW = "최근 7일 새 내러티브 버전·Market Today 회차·Overnight를 근거로 여러 서사를 관통하는 줄기를 묶습니다. 줄기를 주 1회 새로 만드는 단계는 아직 준비 중이라, 지금은 여러 서사를 엮은 큰 서사(군집)를 보여 줍니다. 기준 시각은 근거 중 가장 늦은 것입니다."

/** 줄기 카드 하나 — 번호 · 합니다체 제목 · 관련 서사 칩(이름 v · 날짜, 새로 생긴 서사엔 '새') · 이번 주 Market Today 연결 수와
 *  '다음 갱신 앞당김'(§9.3, §4.25 — 별도 '자주 나온 서사' 카드 대신 줄기 안). 14일 넘으면 흐리게 + '오래됨' */
function StrandCard({ n, m, index }: { n: number; m: WorldMega; index: Map<string, NarrativeItem> }) {
  const old = staleLevel(ageDays(m.created_at)) === "old"
  return (
    <li className={cn("min-w-0 space-y-2 border bg-card p-4", old && "opacity-60")} data-strand data-stale={old || undefined}>
      <div className="flex items-start gap-2">
        <span className="font-mono text-sm tabular-nums text-muted-foreground">{n}</span>
        <p className="min-w-0 flex-1 text-sm font-semibold leading-snug">{m.title ?? m.name}</p>
        {old && <Badge variant="outline" className="shrink-0 text-[10px] font-normal text-muted-foreground">오래됨</Badge>}
      </div>
      <div className="flex flex-wrap gap-1.5 pl-5">
        {m.members.map((t) => {
          const it = index.get(t)
          return (
            <Badge key={t} asChild variant="outline" className="h-6 gap-1 rounded-none text-xs font-normal">
              <Link to={`/narrative?topic=${encodeURIComponent(t)}`}>
                {t}
                {it?.version != null && <span className="font-mono text-[11px] text-muted-foreground">v{it.version} · {kstDay(it.created_at)}</span>}
                {it?.is_new && <span className="text-[11px] text-up">새</span>}
              </Link>
            </Badge>
          )
        })}
      </div>
      {m.mt_topics > 0 && <p className="flex flex-wrap items-center gap-2 pl-5 text-caption text-muted-foreground" data-strand-mt>
        <span className="tabular-nums">Market Today 화두 {m.mt_topics} · {m.mt_sessions}회차</span>
        {m.boost && <Badge className="h-5 rounded-none px-1.5 text-[10px] font-normal">다음 갱신 앞당김</Badge>}
      </p>}
    </li>
  )
}

/**
 * 이번 주 큰 그림 (ia-redesign §4.25) — 머리(기준 시각·근거 범위·AI 종합·어떻게 만드나요?) + 줄기 카드 격자.
 * 줄기 생성 파이프라인(주 1회 LLM)은 아직 없어 줄기 자리에 엮인 큰 서사(메가)를 그린다. 이 카드는 아무것도 생성하지 않는다.
 */
export function BigPictureCard() {
  const q = useBigPicture()
  const index = useNarrativeIndex()
  const d = q.data
  return (
    <Card className="gap-0 bg-[color-mix(in_srgb,var(--primary)_4%,var(--card))] py-0" aria-label="이번 주 큰 그림" data-big-picture>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 pt-4 pb-3">
        <div className="min-w-0">
          <h2 className="text-section font-semibold">이번 주 큰 그림</h2>
          {d && <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-caption text-muted-foreground">
            <span>기준 {kstShort(d.inputs_as_of)}</span>
            <span data-inputs>근거 {inputsLabel(d.inputs)}</span>
          </p>}
        </div>
        <span className="ml-auto flex items-center gap-1.5">
          <InfoTip label="어떻게 만드나요?">{HOW}</InfoTip>
          <Badge variant="outline" className="border-hypothesis/40 text-[10px] font-normal text-hypothesis">AI 종합 · 검증 필요</Badge>
        </span>
      </header>
      <div className="px-4 pb-4">
        {q.isLoading ? <ul className="grid gap-3 md:grid-cols-2" role="status" aria-label="큰 그림 불러오는 중">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)}</ul>
          : q.isError || !d ? <ErrorState message="큰 그림을 불러오지 못했습니다." onRetry={() => void q.refetch()} />
          : d.inputs.narratives === 0 ? <p className="py-4 text-sm text-muted-foreground">이번 주엔 새로 바뀐 서사가 없어요.</p>
          : d.mega.length === 0 ? <p className="py-4 text-sm text-muted-foreground">아직 여러 서사를 엮은 줄기가 없어요.</p>
          : <ul className="grid gap-3 md:grid-cols-2">{d.mega.map((m, i) => <StrandCard key={m.id} n={i + 1} m={m} index={index} />)}</ul>}
      </div>
    </Card>
  )
}

/**
 * 자리 잡은 전제 · 흔들린 전제 (§4.25 전제 칸) — 저장된 세계관 브리핑의 절을 문장 그대로 나눈 목록(서버 `premises`).
 * 7일 넘으면 경고 띠(경과일·그 뒤 새 버전 수·다시 만들기), 14일 넘으면 흐리게 + '오래됨'.
 * '다시 만들기'는 기존 세계관 갱신(POST /knowledge/worldview/compute)을 사람이 누를 때만 부른다 — 자동 갱신 파이프라인은 아직 없다.
 * 검증 지식에서 반례로 충돌 중인 전제(옛 그래프 › 검증 지식)는 접힌 칸으로 함께 둔다.
 */
export function PremisesCard() {
  const q = useBigPicture()
  const qc = useQueryClient()
  const rebuild = useMutation({
    mutationFn: async () => (await api.post("/api/spine/knowledge/worldview/compute", null, { timeout: 300_000 })).data,
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["spine", "world", "big-picture"] }); toast.success("세계관 브리핑을 다시 만들었습니다") },
    onError: () => toast.error("세계관 브리핑을 다시 만들지 못했습니다"),
  })
  const d = q.data
  return (
    <Card className="gap-0 py-0" aria-label="자리 잡은 전제 · 흔들린 전제" id="premises" data-premises>
      <header className="flex flex-wrap items-baseline gap-x-2 border-b px-4 py-3">
        <h2 className="text-section font-semibold">자리 잡은 전제 · 흔들린 전제</h2>
        <span className="text-caption text-muted-foreground">세계관 브리핑{d?.worldview?.created_at ? ` · ${kstDay(d.worldview.created_at)}` : ""}</span>
      </header>
      <div className="space-y-4 p-4">
        {q.isLoading ? <Skeleton className="h-32 w-full" />
          : q.isError || !d ? <ErrorState message="전제를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
          : <PremisesBody d={d} rebuild={() => rebuild.mutate()} pending={rebuild.isPending} />}
        <ContestedKnowledge />
      </div>
    </Card>
  )
}

function PremisesBody({ d, rebuild, pending }: { d: WorldBigPicture; rebuild: () => void; pending: boolean }) {
  const level = staleLevel(d.stale_days)
  const wv = d.worldview
  if (!wv?.briefing) return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      <p>아직 세계관 브리핑이 없습니다.</p>
      <Button size="sm" variant="outline" disabled={pending} onClick={rebuild}>{pending ? "만드는 중…" : "만들기"}</Button>
    </div>
  )
  return <>
    {level !== "fresh" && (
      <div className="flex flex-wrap items-center gap-2 bg-chart-warning/10 px-3 py-2 text-sm" role="note" data-stale-band>
        <p className="min-w-0 flex-1">{kstDay(wv.created_at)}에 만든 뒤 {d.stale_days}일 지났어요.{d.new_versions_since ? ` 그 사이 새 내러티브 버전 ${d.new_versions_since}편이 쌓였어요.` : ""}</p>
        <Button size="sm" disabled={pending} onClick={rebuild}>{pending ? "만드는 중…" : "다시 만들기"}</Button>
      </div>
    )}
    <div className={cn("grid gap-4 md:grid-cols-2", level === "old" && "opacity-60")}>
      <PremiseList title="자리 잡은 전제" items={d.premises.settled} old={level === "old"} />
      <PremiseList title="흔들린 전제" items={d.premises.contested} old={level === "old"} />
    </div>
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="group -ml-2 text-muted-foreground">
          <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />브리핑 전문
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><Markdown>{wv.briefing}</Markdown></CollapsibleContent>
    </Collapsible>
  </>
}

function PremiseList({ title, items, old }: { title: string; items: string[]; old: boolean }) {
  return (
    <section className="min-w-0 space-y-1">
      <h3 className="flex items-center gap-1.5 text-caption font-medium text-muted-foreground">
        {title}{old && <Badge variant="outline" className="text-[10px] font-normal">오래됨</Badge>}
      </h3>
      {items.length === 0 ? <p className="py-2 text-sm text-muted-foreground">-</p>
        : <ul className="divide-y">{items.map((t, i) => <li key={i} className="py-2 text-sm leading-relaxed">{t}</li>)}</ul>}
    </section>
  )
}

/** 검증 지식 중 반례가 쌓여 충돌 중인 것 — 접힌 칸(옛 그래프 › 검증 지식의 '흔들리는 전제') */
function ContestedKnowledge() {
  const q = useContestedPremises()
  const n = q.data?.items.length ?? 0
  if (q.isLoading || q.isError || n === 0) return null
  return (
    <Collapsible className="border-t pt-2">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="group -ml-2 text-muted-foreground">
          <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />검증 지식에서 충돌 중 {n}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><ul className="space-y-3">{q.data!.items.map((k) => <ContestedRow key={k.id} k={k} />)}</ul></CollapsibleContent>
    </Collapsible>
  )
}
