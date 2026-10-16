import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { AlertTriangle, Plus, Sparkles, Trash2 } from "lucide-react"
import { toast } from "sonner"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ErrorState } from "@/components/shared/ErrorState"
import { PageHeader, PageLayout } from "@/components/shared/PageLayout"
import { SparkLine } from "@/components/shared/Spark"
import {
  useAddProxyItem, useCreateProxyBoard, useDeleteProxyBoard, useProxyAdapters, useProxyBoard, useProxyBoards,
  useProxyCatalog, useRemoveProxyItem, useSuggestProxies, type NewItem,
} from "@/hooks/useProxyBoards"
import { cn } from "@/lib/utils"
import { formatLevel, formatPercent } from "@/utils/format"
import type { ProxyBoardItem, ProxyCandidate, ProxyDirection } from "@/types"

/** 단위가 붙은 값 — 원천마다 단위가 다르다(bp·%·$B·pt·원) */
export function proxyValue(v: number | null, unit: string | null) {
  if (v == null) return "-"
  return unit ? `${formatLevel(v)} ${unit}` : formatLevel(v)
}
export function proxyChange(item: Pick<ProxyBoardItem, "latest" | "unit">) {
  const l = item.latest
  if (l.change_pct != null) return formatPercent(l.change_pct)
  if (l.change == null) return "-"
  return `${l.change > 0 ? "+" : ""}${proxyValue(l.change, item.unit)}`
}
const DIR_LABEL: Record<ProxyDirection, string> = { up: "오르면 주의", down: "내리면 주의" }

/**
 * 프록시 보드 — 주제별로 직접 만드는 지표 묶음 (D-240, docs/specs/question-proxy.md §프록시 보드).
 * 읽기는 결정적(LLM 0). 새 보드를 만들 때만 '지표 제안'이 LLM을 1회 쓴다.
 */
export default function ProxyBoardsPage() {
  const [params, setParams] = useSearchParams()
  const boards = useProxyBoards()
  const selected = Number(params.get("board")) || boards.data?.[0]?.id || null
  const [creating, setCreating] = useState(false)
  const pick = (id: number) => setParams(p => { const n = new URLSearchParams(p); n.set("board", String(id)); return n })

  return (
    <PageLayout mode="document" header={<PageHeader title="프록시 보드" description="주제마다 지켜볼 지표를 묶어 매일 원천 데이터로 봅니다"
      actions={<Button size="sm" onClick={() => setCreating(true)}><Plus className="size-3.5" />새 보드</Button>} />}>
      {boards.isPending ? <Skeleton className="h-40 w-full rounded-xl" />
        : boards.isError ? <ErrorState message="보드를 불러오지 못했습니다." onRetry={() => void boards.refetch()} />
        : !boards.data.length ? (
          <Card><CardContent className="space-y-3 py-10 text-center">
            <p className="text-sm text-muted-foreground">아직 보드가 없어요. 예를 들어 'AI 밸류체인 신용·수요'처럼 주제를 적으면 지켜볼 지표를 제안해 드립니다.</p>
            <Button onClick={() => setCreating(true)}><Plus className="size-3.5" />첫 보드 만들기</Button>
          </CardContent></Card>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
            <nav aria-label="보드 목록" className="flex flex-col gap-1">
              {boards.data.map(b => (
                <Button key={b.id} variant="ghost" onClick={() => pick(b.id)} aria-current={b.id === selected ? "true" : undefined}
                  className={cn("h-auto justify-between px-3 py-2 text-left", b.id === selected && "bg-muted")}>
                  <span className="min-w-0 truncate font-medium">{b.name}</span>
                  <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                    {b.in_warn_count > 0 && <Badge variant="outline" className="border-chart-warning/50 text-chart-warning">{b.in_warn_count}</Badge>}
                    {b.item_count}
                  </span>
                </Button>
              ))}
            </nav>
            {selected && <BoardDetail id={selected} />}
          </div>
        )}
      <CreateBoardDialog open={creating} onOpenChange={setCreating} onCreated={id => { setCreating(false); pick(id) }} />
    </PageLayout>
  )
}

function BoardDetail({ id }: { id: number }) {
  const q = useProxyBoard(id)
  const remove = useRemoveProxyItem(id)
  const del = useDeleteProxyBoard()
  const [adding, setAdding] = useState(false)
  if (q.isPending) return <Skeleton className="h-64 w-full rounded-xl" />
  if (q.isError) return <ErrorState message="보드를 불러오지 못했습니다." onRetry={() => void q.refetch()} />
  const b = q.data
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <CardTitle>{b.name}</CardTitle>
          <CardDescription>{b.description || `지표 ${b.item_count}개 중 ${b.in_warn_count}개가 주의 방향으로 움직였어요`}</CardDescription>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}><Plus className="size-3.5" />지표 추가</Button>
          <AlertDialog>
            <AlertDialogTrigger asChild><Button size="sm" variant="ghost" aria-label="보드 삭제"><Trash2 className="size-3.5" /></Button></AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader><AlertDialogTitle>'{b.name}' 보드를 지울까요?</AlertDialogTitle>
                <AlertDialogDescription>보드와 이 보드에서 만든 지표 정의를 지웁니다. 원천 데이터는 그대로입니다.</AlertDialogDescription></AlertDialogHeader>
              <AlertDialogFooter><AlertDialogCancel>취소</AlertDialogCancel>
                <AlertDialogAction onClick={() => del.mutate(id, { onSuccess: () => toast.success("보드를 지웠습니다.") })}>지우기</AlertDialogAction></AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardHeader>
      <CardContent>
        {!b.items.length ? <p className="text-sm text-muted-foreground">지표가 없어요. '지표 추가'로 원천에서 고르세요.</p> : (
          <ul className="divide-y">
            {b.items.map(it => (
              <li key={it.proxy_id} className="grid grid-cols-[minmax(0,1fr)_120px_96px_32px] items-center gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="flex items-center gap-1.5 truncate text-sm font-medium">
                    {it.in_warn && <AlertTriangle className="size-3.5 shrink-0 text-chart-warning" aria-label="주의 방향" />}
                    {it.label}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {it.missing ? "원 질문이 지워져 값이 없어요" : <>{it.adapter_ref ?? "원천 없음"} · {it.latest.as_of ?? "-"}{it.warn_direction && ` · ${DIR_LABEL[it.warn_direction]}`}</>}
                  </p>
                </div>
                <div className="h-7">{it.series.length > 1 && <SparkLine data={it.series.map(p => p.value)} height={28} />}</div>
                <div className="text-right">
                  <p className="text-sm font-semibold tabular-nums">{proxyValue(it.latest.value, it.unit)}</p>
                  <p className={cn("text-xs tabular-nums", it.in_warn ? "text-chart-warning" : "text-muted-foreground")} title={it.latest.change_basis ?? undefined}>{proxyChange(it)}</p>
                </div>
                <Button variant="ghost" size="icon-xs" aria-label={`${it.label} 빼기`} onClick={() => remove.mutate(it.proxy_id)}><Trash2 className="size-3.5" /></Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <AddItemDialog boardId={id} open={adding} onOpenChange={setAdding} />
    </Card>
  )
}

/** 새 보드 — 이름·주제 → 지표 제안(LLM 1회) → 고른 것만 담기 */
function CreateBoardDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (v: boolean) => void; onCreated: (id: number) => void }) {
  const [name, setName] = useState("")
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const suggest = useSuggestProxies()
  const create = useCreateProxyBoard()
  const cands = suggest.data?.candidates ?? []
  const reset = () => { setName(""); setPicked(new Set()); suggest.reset() }
  const toItem = (c: ProxyCandidate): NewItem => ({ label: c.label, adapter: c.adapter, adapter_ref: c.adapter_ref, unit: c.unit, warn_direction: c.warn_direction, rationale: c.rationale })
  const submit = () => create.mutate({ name: name.trim(), items: cands.filter((_, i) => picked.has(i)).map(toItem) }, {
    onSuccess: b => { toast.success(`'${b.name}' 보드를 만들었습니다.`); reset(); onCreated(b.id) },
    onError: e => toast.error(e instanceof Error ? e.message : "보드를 만들지 못했습니다."),
  })
  return (
    <Dialog open={open} onOpenChange={v => { onOpenChange(v); if (!v) reset() }}>
      <DialogContent className="max-w-2xl sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>새 프록시 보드</DialogTitle>
          <DialogDescription>주제를 적고 '지표 제안'을 누르면 지금 있는 데이터에서 지켜볼 지표를 골라 드려요(AI 1회). 고른 것만 담깁니다.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="board-name">보드 주제</Label>
          <div className="flex gap-2">
            <Input id="board-name" value={name} maxLength={80} onChange={e => setName(e.target.value)} placeholder="예: AI 밸류체인 신용·수요" />
            <Button variant="outline" disabled={!name.trim() || suggest.isPending} onClick={() => suggest.mutate(name.trim(), { onSuccess: r => setPicked(new Set(r.candidates.map((_, i) => i))) })}>
              <Sparkles className="size-3.5" />{suggest.isPending ? "제안 중… (1분 안팎)" : "지표 제안"}
            </Button>
          </div>
          {suggest.isError && <p className="text-xs text-destructive">제안을 받지 못했어요. AI 엔진 상태를 확인하거나 지표를 직접 추가하세요.</p>}
        </div>
        {suggest.data && (
          <div className="max-h-[50dvh] space-y-3 overflow-y-auto">
            <ul className="space-y-1.5">
              {cands.map((c, i) => (
                <li key={`${c.adapter_ref}-${i}`} className="flex gap-2.5 rounded-lg border p-2.5">
                  <Checkbox id={`cand-${i}`} checked={picked.has(i)} onCheckedChange={v => setPicked(s => { const n = new Set(s); if (v) n.add(i); else n.delete(i); return n })} className="mt-0.5" />
                  <label htmlFor={`cand-${i}`} className="min-w-0 flex-1 cursor-pointer space-y-0.5">
                    <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">{c.label}
                      {c.lead_or_confirm && <Badge variant="outline" className="text-[10px]">{c.lead_or_confirm === "lead" ? "선행" : "확정"}</Badge>}
                      {c.warn_direction && <Badge variant="outline" className="text-[10px] text-muted-foreground">{DIR_LABEL[c.warn_direction]}</Badge>}
                    </span>
                    <span className="block text-xs text-muted-foreground">{c.source_label} · {c.adapter_ref}</span>
                    {c.rationale && <span className="block text-xs">{c.rationale}</span>}
                  </label>
                </li>
              ))}
            </ul>
            {suggest.data.needs_source.length > 0 && (
              <div className="space-y-1 rounded-lg bg-muted/60 p-3">
                <p className="text-xs font-medium">원천이 없어 담을 수 없는 지표 — 추가 수집이 필요해요</p>
                <ul className="space-y-0.5 text-xs text-muted-foreground">{suggest.data.needs_source.map((n, i) => <li key={i}><span className="text-foreground">{n.label}</span> — {n.reason}</li>)}</ul>
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
          <Button disabled={!name.trim() || create.isPending} onClick={submit}>{picked.size ? `지표 ${picked.size}개로 만들기` : "빈 보드 만들기"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 지표 직접 추가 — 원천 종류 → 카탈로그 검색 → 주의 방향 */
function AddItemDialog({ boardId, open, onOpenChange }: { boardId: number; open: boolean; onOpenChange: (v: boolean) => void }) {
  const adapters = useProxyAdapters()
  const [kind, setKind] = useState<string | null>(null)
  const [q, setQ] = useState("")
  const [warn, setWarn] = useState<ProxyDirection | "">("")
  const catalog = useProxyCatalog(kind, q)
  const add = useAddProxyItem(boardId)
  const choose = (ref: string, label: string, unit: string | null) => add.mutate(
    { label, adapter: kind!, adapter_ref: ref, unit, warn_direction: warn || null },
    { onSuccess: () => { toast.success(`'${label}'을 담았습니다.`); onOpenChange(false) }, onError: e => toast.error(e instanceof Error ? e.message : "담지 못했습니다.") },
  )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl sm:max-w-xl">
        <DialogHeader><DialogTitle>지표 추가</DialogTitle><DialogDescription>원천에서 지표를 고르세요. 값은 매일 원천 데이터에서 읽습니다.</DialogDescription></DialogHeader>
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <div className="space-y-1.5">
            <Label htmlFor="proxy-kind">원천</Label>
            <Select value={kind ?? ""} onValueChange={v => { setKind(v); setQ("") }}>
              <SelectTrigger id="proxy-kind"><SelectValue placeholder="원천 고르기" /></SelectTrigger>
              <SelectContent>{(adapters.data ?? []).map(a => <SelectItem key={a.kind} value={a.kind}>{a.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>주의 방향</Label>
            <ToggleGroup type="single" variant="outline" size="sm" value={warn} onValueChange={v => setWarn(v as ProxyDirection | "")}>
              <ToggleGroupItem value="up">오르면</ToggleGroupItem><ToggleGroupItem value="down">내리면</ToggleGroupItem>
            </ToggleGroup>
          </div>
        </div>
        {kind && (
          <Command shouldFilter={false} className="rounded-lg border">
            <CommandInput value={q} onValueChange={setQ} placeholder="이름·코드로 찾기" />
            <CommandList className="max-h-72">
              <CommandEmpty>{catalog.isFetching ? "찾는 중…" : "맞는 지표가 없어요."}</CommandEmpty>
              <CommandGroup>
                {(catalog.data ?? []).map(c => (
                  <CommandItem key={c.ref} value={c.ref} onSelect={() => choose(c.ref, c.label, c.unit)} disabled={add.isPending}>
                    <span className="min-w-0 flex-1 truncate">{c.label}</span><span className="text-xs text-muted-foreground">{c.ref}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        )}
      </DialogContent>
    </Dialog>
  )
}
