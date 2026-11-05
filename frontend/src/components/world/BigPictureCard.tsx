import { ChevronDown } from "lucide-react"
import { DetailLink as Link } from "@/components/shared/DetailNavigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import { Markdown } from "@/components/shared/Markdown"
import { ContestedRow } from "@/components/world/ContestedPremises"
import type { NarrativeItem } from "@/components/explore/NarrativeList"
import { useBigPicture, useBigPictureRebuild, useContestedPremises, useNarrativeIndex } from "@/hooks/useWorld"
import { ageDays, inputsLabel, kstDay, kstShort, rebuildBlockedReason, STRAND_STATUS_LABEL, staleLevel } from "@/lib/bigPicture"
import { cn } from "@/lib/utils"
import type { StrandStatus, WorldBigPicture, WorldMega, WorldNarrativeChip, WorldPremise, WorldRebuildState, WorldStrand } from "@/types"

const HOW = "최근 7일 새 내러티브 버전을 뼈대로, 그 기간 Market Today 화두와 Overnight 핵심 요약을 근거로 여러 서사를 관통하는 줄기를 AI가 묶습니다. 매주 월요일 07:00에 만들고, 16:00 마감 정리 뒤 지난 생성 이후 새 버전이 3편 이상이면 하루 한 번 더 만듭니다. 근거 줄은 원문을 그대로 옮깁니다. 기준 시각은 근거 중 가장 늦은 것입니다."
const HOW_FALLBACK = HOW + " 첫 생성 전에는 여러 서사를 엮은 큰 서사(군집)를 보여 줍니다."

const STATUS_CLASS: Record<StrandStatus, string> = {
  strengthening: "border-primary/40 text-primary",
  mixed: "border-chart-warning/50 text-chart-warning",
  weakening: "text-muted-foreground",
  new: "border-hypothesis/40 text-hypothesis",
}

/** '다시 만들기' — 쿨다운·한도·엔진 꺼짐이면 비활성 + 이유 툴팁. 누를 때만 POST */
function RebuildButton({ state, label = "다시 만들기", size = "sm", variant = "outline" }: {
  state: WorldRebuildState; label?: string; size?: "sm" | "xs"; variant?: "outline" | "default"
}) {
  const m = useBigPictureRebuild()
  const blocked = rebuildBlockedReason(state)
  const btn = <Button size={size} variant={variant} disabled={!!blocked || m.isPending} onClick={() => m.mutate()} data-rebuild>
    {m.isPending ? "만드는 중…" : label}
  </Button>
  if (!blocked) return btn
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild><span tabIndex={0} className="inline-flex" data-rebuild-blocked={state.reason ?? undefined}>{btn}</span></TooltipTrigger>
        <TooltipContent className="max-w-[260px] text-xs">{blocked}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function NarrativeChips({ chips }: { chips: WorldNarrativeChip[] }) {
  return (
    <div className="flex flex-wrap gap-1.5 pl-5">
      {chips.map((c) => (
        <Badge key={c.narrative_id} asChild variant="outline" className="h-6 gap-1 rounded-none text-xs font-normal">
          <Link to={`/narrative?topic=${encodeURIComponent(c.topic)}`}>
            {c.topic}
            <span className="font-mono text-[11px] text-muted-foreground">v{c.version} · {kstDay(c.created_at)}</span>
            {c.is_new && <span className="text-[11px] text-up">새</span>}
          </Link>
        </Badge>
      ))}
    </div>
  )
}

function MtLine({ topics, sessions, boost }: { topics: number; sessions: number; boost: boolean }) {
  if (topics <= 0) return null
  return (
    <p className="flex flex-wrap items-center gap-2 pl-5 text-caption text-muted-foreground" data-strand-mt>
      <span className="tabular-nums">Market Today 화두 {topics} · {sessions}회차</span>
      {boost && <Badge className="h-5 rounded-none px-1.5 text-[10px] font-normal">다음 갱신 앞당김</Badge>}
    </p>
  )
}

/** 줄기 카드(주간 생성분) — 번호 · 합니다체 제목 · 상태 배지 · 서사 칩 · Market Today 연결 수·앞당김 · 근거 줄(원문 그대로, 출처·회차/날짜) */
function StrandCard({ n, s, old }: { n: number; s: WorldStrand; old: boolean }) {
  return (
    <li className={cn("min-w-0 space-y-2 border bg-card p-4", old && "opacity-60")} data-strand data-status={s.status} data-stale={old || undefined}>
      <div className="flex items-start gap-2">
        <span className="font-mono text-sm tabular-nums text-muted-foreground">{n}</span>
        <p className="min-w-0 flex-1 text-sm font-semibold leading-snug">{s.title}</p>
        {old && <Badge variant="outline" className="shrink-0 text-[10px] font-normal text-muted-foreground">오래됨</Badge>}
        <Badge variant="outline" className={cn("shrink-0 rounded-none text-[10px] font-normal", STATUS_CLASS[s.status])} data-strand-status>
          {STRAND_STATUS_LABEL[s.status]}
        </Badge>
      </div>
      <NarrativeChips chips={s.narratives} />
      <MtLine topics={s.mt_topics} sessions={s.mt_sessions} boost={s.boost} />
      {s.evidence.length > 0 && (
        <ul className="space-y-1 border-t pt-2 pl-5" data-strand-evidence>
          {s.evidence.map((e) => (
            <li key={e.ref} className="flex min-w-0 gap-2 text-caption leading-snug">
              <span className="shrink-0 text-muted-foreground">{e.label}</span>
              <span className="min-w-0 break-words">{e.text}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

/** 첫 생성 전 — 엮인 큰 서사(메가)를 줄기 자리에 그린다(옛 표시 그대로). 14일 넘으면 흐리게 + '오래됨' */
function MegaCard({ n, m, index }: { n: number; m: WorldMega; index: Map<string, NarrativeItem> }) {
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
 * 이번 주 큰 그림 (ia-redesign §4.25) — 머리(기준 시각·근거 범위·AI 종합·어떻게 만드나요?·다시 만들기) + 줄기 카드 격자.
 * 주간 생성분(pipeline/weekly_big_picture)을 읽기만 한다. 7일 넘으면 경고 띠(경과일·그 뒤 새 버전·다시 만들기), 14일 넘으면 흐리게 + '오래됨'.
 * 첫 생성 전(source='mega')에는 엮인 큰 서사(메가)를 줄기 자리에 그린다.
 */
export function BigPictureCard() {
  const q = useBigPicture()
  const index = useNarrativeIndex()
  const d = q.data
  const generated = d?.source === "generated"
  const level = generated ? staleLevel(d?.stale_days) : "fresh"
  return (
    <Card className="gap-0 bg-[color-mix(in_srgb,var(--primary)_4%,var(--card))] py-0" aria-label="이번 주 큰 그림" data-big-picture data-source={d?.source}>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 pt-4 pb-3">
        <div className="min-w-0">
          <h2 className="text-section font-semibold">이번 주 큰 그림</h2>
          {d && <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-caption text-muted-foreground">
            <span>기준 {kstShort(d.inputs_as_of)}</span>
            <span data-inputs>근거 {inputsLabel(d.inputs)}</span>
          </p>}
        </div>
        <span className="ml-auto flex items-center gap-1.5">
          <InfoTip label="어떻게 만드나요?">{generated ? HOW : HOW_FALLBACK}</InfoTip>
          <Badge variant="outline" className="border-hypothesis/40 text-[10px] font-normal text-hypothesis">AI 종합 · 검증 필요</Badge>
          {d && level === "fresh" && <RebuildButton state={d.rebuild} label={generated ? "다시 만들기" : "만들기"} size="xs" />}
        </span>
      </header>
      {d && level !== "fresh" && (
        <div className="mx-4 mb-3 flex flex-wrap items-center gap-2 bg-chart-warning/10 px-3 py-2 text-sm" role="note" data-stale-band>
          <p className="min-w-0 flex-1">{d.stale_days}일 지났어요{d.new_versions_since ? ` · 그 사이 새 버전 ${d.new_versions_since}편` : ""}</p>
          <RebuildButton state={d.rebuild} variant="default" />
        </div>
      )}
      <div className="px-4 pb-4">
        {q.isLoading ? <ul className="grid gap-3 md:grid-cols-2" role="status" aria-label="큰 그림 불러오는 중">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)}</ul>
          : q.isError || !d ? <ErrorState message="큰 그림을 불러오지 못했습니다." onRetry={() => void q.refetch()} />
          : generated ? <ul className="grid gap-3 md:grid-cols-2">{d.strands.map((s, i) => <StrandCard key={i} n={i + 1} s={s} old={level === "old"} />)}</ul>
          : d.inputs.narratives === 0 ? <p className="py-4 text-sm text-muted-foreground">이번 주엔 새로 바뀐 서사가 없어요.</p>
          : d.mega.length === 0 ? <p className="py-4 text-sm text-muted-foreground">아직 여러 서사를 엮은 줄기가 없어요.</p>
          : <ul className="grid gap-3 md:grid-cols-2">{d.mega.map((m, i) => <MegaCard key={m.id} n={i + 1} m={m} index={index} />)}</ul>}
      </div>
    </Card>
  )
}

/**
 * 자리 잡은 전제 · 흔들린 전제 (§4.25 전제 칸) — 주간 큰 그림 생성분의 전제(같은 실행에서 함께 갱신).
 * 흔들린 전제에 이번 주 서사가 부딪혔으면 '이번 주 흔들림' 배지 + 출처 서사 한 줄(원문에서 확인된 인용).
 * 첫 생성 전에는 저장된 세계관 브리핑의 절을 문장 그대로(7일 넘으면 경고 띠, 14일 넘으면 '오래됨'). '다시 만들기'·'만들기'는 큰 그림 생성.
 * 검증 지식에서 반례로 충돌 중인 전제(옛 그래프 › 검증 지식)는 접힌 칸으로 함께 둔다.
 */
export function PremisesCard() {
  const q = useBigPicture()
  const d = q.data
  const generated = d?.source === "generated"
  const stamp = generated ? d?.generated_at : d?.worldview?.created_at
  return (
    <Card className="gap-0 py-0" aria-label="자리 잡은 전제 · 흔들린 전제" id="premises" data-premises>
      <header className="flex flex-wrap items-baseline gap-x-2 border-b px-4 py-3">
        <h2 className="text-section font-semibold">자리 잡은 전제 · 흔들린 전제</h2>
        {d && <span className="text-caption text-muted-foreground">{generated ? "이번 주 큰 그림" : "세계관 브리핑"}{stamp ? ` · ${kstDay(stamp)}` : ""}</span>}
      </header>
      <div className="space-y-4 p-4">
        {q.isLoading ? <Skeleton className="h-32 w-full" />
          : q.isError || !d ? <ErrorState message="전제를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
          : <PremisesBody d={d} />}
        <ContestedKnowledge />
      </div>
    </Card>
  )
}

function PremisesBody({ d }: { d: WorldBigPicture }) {
  const generated = d.source === "generated"
  const level = staleLevel(d.stale_days)
  const wv = d.worldview
  const empty = d.premises.settled.length + d.premises.contested.length === 0
  if (!generated && !wv?.briefing) return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      <p>아직 전제 목록이 없습니다.</p>
      <RebuildButton state={d.rebuild} label="만들기" />
    </div>
  )
  return <>
    {/* 생성분의 낡음 띠는 큰 그림 머리에 한 번만 — 여기선 첫 생성 전(세계관 브리핑)만 */}
    {!generated && level !== "fresh" && wv && (
      <div className="flex flex-wrap items-center gap-2 bg-chart-warning/10 px-3 py-2 text-sm" role="note" data-stale-band>
        <p className="min-w-0 flex-1">{kstDay(wv.created_at)}에 만든 뒤 {d.stale_days}일 지났어요.{d.new_versions_since ? ` 그 사이 새 내러티브 버전 ${d.new_versions_since}편이 쌓였어요.` : ""}</p>
        <RebuildButton state={d.rebuild} variant="default" />
      </div>
    )}
    {generated && empty ? <p className="py-2 text-sm text-muted-foreground">이번 큰 그림엔 전제가 없습니다.</p>
      : <div className={cn("grid gap-4 md:grid-cols-2", level === "old" && "opacity-60")}>
        <PremiseList title="자리 잡은 전제" items={d.premises.settled} old={level === "old"} />
        <PremiseList title="흔들린 전제" items={d.premises.contested} old={level === "old"} />
      </div>}
    {!generated && wv?.briefing && <Collapsible>
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="group -ml-2 text-muted-foreground">
          <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" />브리핑 전문
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><Markdown>{wv.briefing}</Markdown></CollapsibleContent>
    </Collapsible>}
  </>
}

function PremiseList({ title, items, old }: { title: string; items: WorldPremise[]; old: boolean }) {
  return (
    <section className="min-w-0 space-y-1">
      <h3 className="flex items-center gap-1.5 text-caption font-medium text-muted-foreground">
        {title}{old && <Badge variant="outline" className="text-[10px] font-normal">오래됨</Badge>}
      </h3>
      {items.length === 0 ? <p className="py-2 text-sm text-muted-foreground">-</p>
        : <ul className="divide-y">{items.map((p, i) => (
          <li key={i} className="space-y-1 py-2 text-sm leading-relaxed" data-premise>
            <p>{p.text}{p.shaken_by && <Badge variant="outline" className="ml-1.5 border-chart-warning/50 align-middle text-[10px] font-normal text-chart-warning" data-shaken>이번 주 흔들림</Badge>}</p>
            {p.shaken_by && <p className="text-caption text-muted-foreground">
              <Link to={`/narrative?topic=${encodeURIComponent(p.shaken_by.topic)}`} className="hover:underline">{p.shaken_by.topic} v{p.shaken_by.version}({kstDay(p.shaken_by.created_at)})</Link>
              {" "}“{p.shaken_by.quote}”
            </p>}
          </li>
        ))}</ul>}
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
