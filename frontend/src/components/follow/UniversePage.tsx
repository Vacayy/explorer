import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { FileText, Loader2, Plus, Sparkles, Star, X } from "lucide-react"
import { apiQuery, STALE } from "@/api/query"
import api from "@/api/client"
import {
  useIndustryGroups,
  useIndustryDetail,
  useCreateGroup,
  useProposeMembers,
  useAddMember,
  useRemoveMember,
} from "@/hooks/useIndustry"
import { useWatchlist, useAddToWatchlist, useDeleteWatchlistItem } from "@/hooks/useWatchlist"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { PageContainer } from "@/components/shared/PageContainer"
import { EmptyState } from "@/components/shared/ErrorState"
import { formatKrw } from "@/utils/format"
import type { IndustryMember, IndustryCandidate } from "@/types"

const CATEGORY_OPTIONS = ["소재", "부품", "장비", "완제품", "서비스", "기타"]

/**
 * /follow/universe — 담당 섹터 커버리지(밸류체인) 큐레이션.
 * 기계가 후보 제안 → 사람이 체크·승인. 산업 그룹 → 밸류체인 단계(category)별 멤버.
 */
export default function UniversePage() {
  const { data: groups = [], isLoading: groupsLoading } = useIndustryGroups()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [proposeOpen, setProposeOpen] = useState(false)

  // 첫 그룹 자동 선택
  const activeId = selectedId ?? groups[0]?.id ?? null

  const { data: detail, isLoading: detailLoading } = useIndustryDetail(activeId)
  const removeMember = useRemoveMember(activeId ?? 0)

  // 팔로우(watchlist) 연결 — 커버리지 중 '능동 추적'을 ★로 표시 (역할 분리, 겹침 해소)
  const { data: watchlist = [] } = useWatchlist()
  const addFollow = useAddToWatchlist()
  const delFollow = useDeleteWatchlistItem()
  const followById = useMemo(
    () => new Map(watchlist.map((w) => [w.stock_code, w.id])), [watchlist])
  const toggleFollow = (code: string) => {
    const id = followById.get(code)
    if (id != null) delFollow.mutate(id)
    else addFollow.mutate({ stock_code: code })
  }

  // 멤버를 category별로 묶고 시총 합 내림차순 정렬
  const grouped = useMemo(() => {
    if (!detail) return []
    const map: Record<string, IndustryMember[]> = {}
    for (const m of detail.members) {
      ;(map[m.category] ??= []).push(m)
    }
    for (const cat of Object.keys(map)) {
      map[cat].sort(
        (a, b) => (b.latest_market_cap ?? 0) - (a.latest_market_cap ?? 0),
      )
    }
    return Object.entries(map)
      .map(([cat, members]) => ({
        cat,
        members,
        totalMcap: members.reduce((s, m) => s + (m.latest_market_cap ?? 0), 0),
      }))
      .sort((a, b) => b.totalMcap - a.totalMcap)
  }, [detail])

  return (
    <PageContainer>
      {/* 헤더 */}
      <div className="flex items-start gap-3">
        <div>
          <h2 className="text-xl font-bold">유니버스</h2>
          <p className="text-sm text-muted-foreground">담당 섹터 커버리지 · 밸류체인</p>
        </div>
        <Button size="sm" className="ml-auto" onClick={() => setCreateOpen(true)}>
          <Plus data-icon="inline-start" />
          새 산업 그룹
        </Button>
      </div>

      {/* 그룹 0개 → 안내 */}
      {!groupsLoading && groups.length === 0 && (
        <div className="py-16 text-center space-y-3">
          <p className="text-sm text-muted-foreground">
            아직 산업 그룹이 없습니다 — 담당 섹터의 밸류체인을 만들어보세요.
          </p>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus data-icon="inline-start" />
            새 산업 그룹
          </Button>
        </div>
      )}

      {groupsLoading && (
        <div className="flex gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-7 w-24 rounded-full" />
          ))}
        </div>
      )}

      {/* 그룹 pill 선택 */}
      {groups.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {groups.map((g) => (
            <Button
              key={g.id}
              size="sm"
              variant={g.id === activeId ? "default" : "outline"}
              onClick={() => setSelectedId(g.id)}
              className="rounded-full h-7"
            >
              {g.name}
            </Button>
          ))}
        </div>
      )}

      {/* 선택된 그룹 */}
      {activeId !== null && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            {detail?.group.description && (
              <p className="text-sm text-muted-foreground">{detail.group.description}</p>
            )}
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              onClick={() => setProposeOpen(true)}
            >
              <Sparkles data-icon="inline-start" />
              종목 후보 제안
            </Button>
          </div>

          {detailLoading && (
            <div className="space-y-3">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          )}

          {!detailLoading && detail && detail.members.length === 0 && (
            <EmptyState message="이 그룹엔 종목이 없습니다 — '종목 후보 제안'으로 추가하세요." />
          )}

          {!detailLoading &&
            grouped.map(({ cat, members, totalMcap }) => (
              <div key={cat} className="space-y-2">
                <div className="flex items-baseline gap-2">
                  <h3 className="text-sm font-semibold">{cat}</h3>
                  <span className="text-xs text-muted-foreground">
                    {members.length}종목{totalMcap > 0 ? ` · ${formatKrw(totalMcap)}` : ""}
                  </span>
                </div>
                <MemberTable members={members} onRemove={(id) => removeMember.mutate(id)}
                  followById={followById} onToggleFollow={toggleFollow} />
              </div>
            ))}

          {!detailLoading && (
            <SectorNarratives groupId={activeId} groupName={detail?.group.name ?? ""} />
          )}
        </div>
      )}

      <CreateGroupDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => setSelectedId(id)}
      />
      {activeId !== null && (
        <ProposeDialog
          groupId={activeId}
          open={proposeOpen}
          onOpenChange={setProposeOpen}
        />
      )}
    </PageContainer>
  )
}

/* ── 이 섹터의 내러티브 (섹터 집약 뷰, D-074 Phase 1) — 파편화된 topic 내러티브가 섹터 단위로 모임 ── */

interface SectorNarr {
  id: number; topic: string; title: string | null; co_docs: number; relevance: number
}

function SectorNarratives({ groupId, groupName }: { groupId: number; groupName: string }) {
  const navigate = useNavigate()
  const { data = [], isLoading } = useQuery(
    apiQuery<SectorNarr[]>({
      key: ["industries", groupId, "narratives"],
      url: `/api/industries/${groupId}/narratives`, staleTime: STALE.short,
    }),
  )
  const genReport = useMutation({
    mutationFn: () => api.post(`/api/spine/report/compute-group?group_id=${groupId}`),
    onSuccess: (r) => {
      const st = (r.data as { status?: string }).status
      if (st === "ok") { toast.success("섹터 리포트 생성됨"); navigate(`/report?topic=${encodeURIComponent(groupName)}`) }
      else toast("섹터에 집약할 내러티브가 부족합니다")
    },
    onError: () => toast.error("리포트 생성 실패 — 다시 시도"),
  })
  if (isLoading || data.length === 0) return null
  return (
    <div className="space-y-2 border-t pt-4">
      <div className="flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">이 섹터의 내러티브</h3>
        <span className="text-[11px] text-muted-foreground">
          이 섹터 종목을 다루는 내러티브가 모임 · 한 내러티브는 여러 섹터에 등장(공동언급 기반, 관련도순)
        </span>
        <span className="ml-auto flex items-center gap-2 shrink-0">
          <Link to={`/report?topic=${encodeURIComponent(groupName)}`}
            className="text-[11px] text-muted-foreground hover:text-primary inline-flex items-center gap-1">
            <FileText className="h-3 w-3" /> 리포트 보기
          </Link>
          <Button size="xs" variant="outline" disabled={genReport.isPending} onClick={() => genReport.mutate()}>
            {genReport.isPending
              ? <><Loader2 className="h-3 w-3 animate-spin" /> 생성 중… (수 분)</>
              : <>섹터 리포트 생성</>}
          </Button>
        </span>
      </div>
      <div className="space-y-1.5">
        {data.map((n) => (
          <Link key={n.id} to={`/narrative?topic=${encodeURIComponent(n.topic)}`}
            className="flex items-center gap-2 rounded-md border px-3 py-2 hover:border-primary transition-colors">
            <Badge variant="secondary" className="text-[10px] shrink-0">{n.topic}</Badge>
            <span className="text-[13px] truncate flex-1">{n.title || n.topic}</span>
            <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums" title="공동언급 문서 · 관련도">
              {n.co_docs}건 · {Math.round(n.relevance * 100)}%
            </span>
          </Link>
        ))}
      </div>
    </div>
  )
}

/* ── 멤버 테이블 (밸류체인 단계별) — 팔로우 종목 테이블과 동형 ── */

function MemberTable({ members, onRemove, followById, onToggleFollow }: {
  members: IndustryMember[]
  onRemove: (id: number) => void
  followById: Map<string, number>
  onToggleFollow: (code: string) => void
}) {
  const num = (v: number | null, suffix: string, digits = 1) =>
    v != null ? `${v.toFixed(digits)}${suffix}` : "-"
  return (
    <div className="rounded-lg border overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <TableHead className="w-8" />
            <TableHead>종목</TableHead>
            <TableHead className="text-right">시총</TableHead>
            <TableHead className="text-right">PER</TableHead>
            <TableHead className="text-right">PBR</TableHead>
            <TableHead className="text-right">영업이익률</TableHead>
            <TableHead className="text-right">ROE</TableHead>
            <TableHead className="w-8" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((m) => {
            const followed = followById.has(m.stock_code)
            return (
            <TableRow key={m.id} className="group">
              <TableCell>
                <Button variant="ghost" size="icon" className="size-6"
                  onClick={() => onToggleFollow(m.stock_code)}
                  aria-label={followed ? "팔로우 해제" : "팔로우 — 능동 추적에 추가"}
                  title={followed ? "팔로우 중 (능동 추적) — 클릭해 해제" : "팔로우 — 논지·목표가로 능동 추적"}>
                  <Star className={cn("h-3.5 w-3.5", followed ? "fill-primary text-primary" : "text-muted-foreground/50")} />
                </Button>
              </TableCell>
              <TableCell>
                <Link to={`/analyze/${m.stock_code}/summary`} className="text-sm font-medium hover:underline">
                  {m.corp_name}
                </Link>
                <span className="ml-2 text-[11px] text-muted-foreground tabular-nums">{m.stock_code}</span>
              </TableCell>
              <TableCell className="text-right tabular-nums text-xs">
                {m.latest_market_cap != null ? formatKrw(m.latest_market_cap) : "-"}
              </TableCell>
              <TableCell className="text-right tabular-nums text-xs">{num(m.per, "배")}</TableCell>
              <TableCell className="text-right tabular-nums text-xs">{num(m.pbr, "배", 2)}</TableCell>
              <TableCell className="text-right tabular-nums text-xs">{num(m.op_margin, "%")}</TableCell>
              <TableCell className="text-right tabular-nums text-xs">{num(m.roe, "%")}</TableCell>
              <TableCell className="text-right">
                <Button variant="ghost" size="icon" onClick={() => onRemove(m.id)} aria-label="멤버 삭제"
                  className="size-6 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive">
                  <X className="h-3.5 w-3.5" />
                </Button>
              </TableCell>
            </TableRow>
          )})}
        </TableBody>
      </Table>
    </div>
  )
}

/* ── 새 산업 그룹 다이얼로그 ── */

function CreateGroupDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: (id: number) => void
}) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const create = useCreateGroup()

  const submit = async () => {
    if (!name.trim()) return
    const group = await create.mutateAsync({
      name: name.trim(),
      description: description.trim() || undefined,
    })
    onCreated(group.id)
    setName("")
    setDescription("")
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>새 산업 그룹</DialogTitle>
          <DialogDescription>담당할 섹터의 밸류체인 그룹을 만듭니다.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input
            placeholder="그룹 이름 (예: 반도체)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <Input
            placeholder="설명 (선택)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={create.isPending}
          >
            취소
          </Button>
          <Button onClick={submit} disabled={!name.trim() || create.isPending}>
            {create.isPending ? "생성 중…" : "생성"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── 종목 후보 제안 다이얼로그 ── */

interface Selection {
  checked: boolean
  category: string
}

function ProposeDialog({
  groupId,
  open,
  onOpenChange,
}: {
  groupId: number
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { data: candidates = [], isLoading } = useProposeMembers(groupId, open)
  const addMember = useAddMember(groupId)
  const [sel, setSel] = useState<Record<string, Selection>>({})
  const [adding, setAdding] = useState(false)

  const setChecked = (code: string, checked: boolean) =>
    setSel((s) => ({
      ...s,
      [code]: { category: s[code]?.category ?? "기타", checked },
    }))
  const setCategory = (code: string, category: string) =>
    setSel((s) => ({
      ...s,
      [code]: { checked: s[code]?.checked ?? false, category },
    }))

  const chosen = candidates.filter((c) => sel[c.stock_code]?.checked)

  const submit = async () => {
    setAdding(true)
    try {
      for (const c of chosen) {
        await addMember.mutateAsync({
          stock_code: c.stock_code,
          category: sel[c.stock_code]?.category ?? "기타",
        })
      }
      setSel({})
      onOpenChange(false)
    } finally {
      setAdding(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>종목 후보 제안</DialogTitle>
          <DialogDescription>
            기계가 제안한 후보입니다 (RS 내림차순, 노이즈 포함) — 체크로 거른 뒤 밸류체인 단계를 지정하세요.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[50vh] overflow-y-auto space-y-1">
          {isLoading && (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          )}
          {!isLoading && candidates.length === 0 && (
            <EmptyState message="제안할 후보가 없습니다." />
          )}
          {!isLoading &&
            candidates.map((c) => (
              <CandidateRow
                key={c.stock_code}
                candidate={c}
                checked={sel[c.stock_code]?.checked ?? false}
                category={sel[c.stock_code]?.category ?? "기타"}
                onCheckedChange={(v) => setChecked(c.stock_code, v)}
                onCategoryChange={(v) => setCategory(c.stock_code, v)}
              />
            ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={adding}>
            취소
          </Button>
          <Button onClick={submit} disabled={chosen.length === 0 || adding}>
            {adding ? "추가 중…" : `선택 추가${chosen.length > 0 ? ` (${chosen.length})` : ""}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CandidateRow({
  candidate: c,
  checked,
  category,
  onCheckedChange,
  onCategoryChange,
}: {
  candidate: IndustryCandidate
  checked: boolean
  category: string
  onCheckedChange: (v: boolean) => void
  onCategoryChange: (v: string) => void
}) {
  return (
    <label className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-muted/50 cursor-pointer">
      <Checkbox
        checked={checked}
        onCheckedChange={(v) => onCheckedChange(v === true)}
      />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium truncate">{c.name}</div>
        <div className="flex flex-wrap gap-1 mt-0.5">
          {c.rs_short != null && (
            <Badge variant="outline" className="text-[11px]">
              RS {c.rs_short.toFixed(1)}
            </Badge>
          )}
          <Badge variant="outline" className="text-[11px]">
            관련도 {Math.round(c.relevance * 100)}%
          </Badge>
          {c.pos_52w != null && (
            <Badge variant="outline" className="text-[11px]">
              52주 {c.pos_52w.toFixed(0)}%
            </Badge>
          )}
          {c.per != null && (
            <Badge variant="outline" className="text-[11px]">
              PER {c.per.toFixed(1)}배
            </Badge>
          )}
          {c.market_cap != null && (
            <Badge variant="secondary" className="text-[11px]">
              {formatKrw(c.market_cap)}
            </Badge>
          )}
        </div>
      </div>
      <div onClick={(e) => e.preventDefault()}>
        <Select value={category} onValueChange={onCategoryChange}>
          <SelectTrigger className="h-8 w-24 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CATEGORY_OPTIONS.map((opt) => (
              <SelectItem key={opt} value={opt}>
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </label>
  )
}
