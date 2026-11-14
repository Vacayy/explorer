import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ErrorState } from "@/components/shared/ErrorState"
import { InfoTip } from "@/components/shared/InfoTip"
import FilterChips from "@/components/shared/FilterChips"
import { Section } from "@/components/follow/season/seasonUi"
import { CurationApplySwitch, NEXT_CURATION_LABEL } from "@/components/admin/adminUi"
import { useCurationLog } from "@/hooks/useAdmin"
import { cn } from "@/lib/utils"
import { formatKstDateTime, formatNumber } from "@/utils/format"
import type { CurationEntry } from "@/types"

/**
 * 관리자 › 자동 정리 (/admin?view=curation · 시안 Admin-Curation · ia-redesign §4.31, D-294·D-295).
 * 기록 보기다 — 사용자가 처리할 목록이 아니고, 누르는 것은 '적용' 스위치 하나뿐(되돌리기 버튼은 되돌리기 기능을 만들 때).
 * 필터는 URL(`kind`·`verdict`), 목록은 처음 20줄 + 더 보기.
 */
const KINDS: [string, string][] = [["alias", "별칭"], ["vocab_merge", "노드 병합"], ["knowledge", "지식 승격"], ["person", "인물 이름"]]
const KIND_LABEL: Record<string, string> = Object.fromEntries(KINDS)
const VERDICTS: [string, string][] = [["approve", "승인"], ["reject", "거부"], ["hold", "보류"], ["skip", "건너뜀"]]
const VERDICT_LABEL = Object.fromEntries(VERDICTS)
const VERDICT_CLS: Record<string, string> = {
  approve: "bg-fact-tint text-fact", reject: "bg-down-tint text-down-ink", hold: "bg-chip text-ink-2", skip: "bg-chip text-ink-3",
}
const PAGE = 20

export function CurationPanel() {
  const [params, setParams] = useSearchParams()
  const kind = KIND_LABEL[params.get("kind") ?? ""] ? params.get("kind") : null
  const verdict = VERDICT_LABEL[params.get("verdict") ?? ""] ? params.get("verdict") : null
  const all = useCurationLog(null, null)
  const list = useCurationLog(kind, verdict)
  const setFilter = (key: "kind" | "verdict", v: string) => {
    const next = new URLSearchParams(params)
    if (v === "all") next.delete(key); else next.set(key, v)
    setParams(next, { replace: true })
  }

  if (all.isPending) return <div className="space-y-4"><Skeleton className="h-20 w-full rounded-card" /><Skeleton className="h-48 w-full rounded-card" /><Skeleton className="h-72 w-full rounded-card" /></div>
  if (all.isError) return <ErrorState message="자동 정리 기록을 불러오지 못했습니다." onRetry={() => all.refetch()} retrying={all.isFetching} />
  const d = all.data
  const total = Object.values(d.counts).reduce((a, v) => a + Object.values(v).reduce((x, y) => x + y, 0), 0)
  const byVerdict = (v: string) => Object.values(d.counts).reduce((a, k) => a + (k[v] ?? 0), 0)
  const byKind = (k: string) => Object.values(d.counts[k] ?? {}).reduce((a, n) => a + n, 0)
  const last = d.items[0]?.decided_at

  return (
    <div className="space-y-4">
      <Section title="지금 단계" note={`${last ? `마지막 판정 ${formatKstDateTime(last)} · ` : ""}${NEXT_CURATION_LABEL}`}>
        <div className="flex min-h-11 flex-wrap items-center gap-2 border bg-muted/40 px-3 py-2">
          <Badge variant="outline" className={d.apply_enabled ? "text-fact border-fact/40" : "text-muted-foreground"}>{d.apply_enabled ? "적용 중" : "판정만 기록 중"}</Badge>
          <InfoTip label="지금 단계 설명">
            {d.apply_enabled
              ? "판정대로 별칭·노드 병합·지식 승격을 처리하고 있습니다. 끄면 다음 판정부터 기록만 남깁니다."
              : "판정 결과만 남기고 별칭·병합·지식은 바꾸지 않습니다. 기록을 보고 적용을 켜면 그때부터 판정대로 처리합니다."}
          </InfoTip>
          <span className="ml-auto text-sm">적용</span>
          <CurationApplySwitch enabled={d.apply_enabled} />
        </div>
      </Section>

      <Section title="판정 집계" note={`모두 ${formatNumber(total)}건`}>
        <Table>
          <TableHeader><TableRow>
            <TableHead>종류</TableHead>
            {VERDICTS.map(([v, l]) => <TableHead key={v} className="text-right">{l}</TableHead>)}
          </TableRow></TableHeader>
          <TableBody>
            {KINDS.map(([k, l]) => (
              <TableRow key={k}>
                <TableCell className="text-sm">{l}</TableCell>
                {VERDICTS.map(([v]) => <TableCell key={v} className="text-right font-mono tabular-nums">{formatNumber(d.counts[k]?.[v] ?? 0)}</TableCell>)}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>

      <Section title={<>판정 기록<InfoTip label="판정 기록 설명">최근 판정 순입니다. 11/04 이전에 하나씩 검토한 994건은 이 기록 이전입니다(D-294). 노드 병합은 적용할 때 흡수되는 엔티티 행과 연결 위치를 남겨 되돌릴 수 있게 합니다.</InfoTip></>}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <FilterChips value={verdict ?? "all"} onChange={v => setFilter("verdict", v)}
            options={[{ value: "all", label: `전체 ${formatNumber(total)}` }, ...VERDICTS.map(([v, l]) => ({ value: v, label: `${l} ${formatNumber(byVerdict(v))}` }))]} />
          <span aria-hidden="true" className="h-[18px] w-px bg-line-2 max-sm:hidden" />
          <FilterChips value={kind ?? "all"} onChange={v => setFilter("kind", v)}
            options={[{ value: "all", label: "모든 종류" }, ...KINDS.map(([k, l]) => ({ value: k, label: `${l} ${formatNumber(byKind(k))}` }))]} />
        </div>
        <CurationList key={`${kind}-${verdict}`} q={list} empty={total === 0 ? "아직 판정한 정리 작업이 없습니다" : "이 조건의 판정이 없습니다"} />
      </Section>
    </div>
  )
}

function CurationList({ q, empty }: { q: ReturnType<typeof useCurationLog>; empty: string }) {
  const [open, setOpen] = useState(false)
  if (q.isPending) return <div className="space-y-2">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-12 w-full" />)}</div>
  if (q.isError) return <ErrorState message="판정 기록을 불러오지 못했습니다." onRetry={() => q.refetch()} retrying={q.isFetching} />
  const items = q.data.items
  if (!items.length) return <p className="py-6 text-center text-sm text-muted-foreground">{empty}</p>
  const shown = open ? items : items.slice(0, PAGE)
  return (
    <>
      <ul className={cn("-mx-(--card-spacing) divide-y border-t", q.isPlaceholderData && "opacity-60")}>
        {shown.map(e => <CurationRow key={`${e.kind}-${e.target_id}`} e={e} />)}
      </ul>
      {items.length > PAGE && (
        <Button variant="ghost" size="sm" className="self-center text-muted-foreground" onClick={() => setOpen(v => !v)}>
          {open ? "접기" : `${formatNumber(items.length - PAGE)}건 더 보기`}
        </Button>
      )}
    </>
  )
}

function CurationRow({ e }: { e: CurationEntry }) {
  return (
    <li className="flex flex-col gap-1 px-(--card-spacing) py-2.5 md:grid md:grid-cols-[88px_minmax(0,1fr)_auto] md:items-start md:gap-x-3.5">
      {/* 모바일: 종류 | 판정만·시각 한 줄 → 대상. 데스크톱: 종류 | 대상 | 판정만·시각 */}
      <div className="flex items-baseline justify-between gap-2 md:contents">
        <span className="text-xs text-ink-3 md:order-1 md:pt-0.5">{KIND_LABEL[e.kind] ?? e.kind}</span>
        <div className="whitespace-nowrap text-right text-xs md:order-3">
          <span className={e.applied ? "text-fact" : "text-muted-foreground"}>{e.applied ? "적용됨" : "판정만"}</span>
          <span className="ml-1.5 font-mono tabular-nums text-muted-foreground md:ml-0 md:block">{formatKstDateTime(e.decided_at)}</span>
        </div>
      </div>
      <div className="min-w-0 md:order-2">
        <p className="line-clamp-2 text-[13.5px] leading-normal md:truncate">{e.title}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-2">
          <span className={cn("inline-flex h-[22px] items-center rounded-md px-2 text-xs font-medium", VERDICT_CLS[e.verdict])}>{VERDICT_LABEL[e.verdict] ?? e.verdict}</span>
          {e.rule && <span className="min-w-0 break-all">{e.rule}</span>}
          {e.kind === "vocab_merge" && e.applied && <Badge variant="outline" className="text-[10px]">되돌리기 재료 있음</Badge>}
        </div>
      </div>
    </li>
  )
}
