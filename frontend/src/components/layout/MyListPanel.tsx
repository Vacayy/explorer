import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { apiQuery } from "@/api/query"
import {
  Sidebar, SidebarContent, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarMenu,
  SidebarMenuButton, SidebarMenuItem, SidebarMenuSkeleton,
} from "@/components/ui/sidebar"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Button } from "@/components/ui/button"
import { useGroup, useGroups } from "@/hooks/useGroups"
import { useSaved } from "@/hooks/useSaved"
import { readRecentStocks } from "@/lib/recentStocks"
import { PREF, readPref, writePref } from "@/lib/shellPrefs"
import { cn } from "@/lib/utils"
import { formatPercent } from "@/utils/format"

/**
 * 내 목록 — 종목 묶음 · 최근 본 종목 · 팔로우 인물 · 저장됨 (docs/specs/app-shell.md §4).
 * 관심 종목의 진실원천은 stock_groups. 소스(채널·블로그) 목록은 캔버스 › 소스로 옮겼다.
 */
export function MyListPanel({ currentStockCode }: { currentStockCode: string | null }) {
  return (
    <Sidebar side="left" collapsible="offcanvas" aria-label="내 목록"
      className="top-(--topbar-height) h-[calc(100svh-var(--topbar-height))]">
      <SidebarContent className="gap-0 py-2">
        <GroupsSection currentStockCode={currentStockCode} />
        <RecentSection currentStockCode={currentStockCode} />
        <PeopleSection />
        <SavedSection />
      </SidebarContent>
    </Sidebar>
  )
}

const dossierPath = (code: string, market?: string | null) =>
  market === "us" || /^[A-Z.]+$/.test(code) ? `/us/${code}` : `/analyze/${code}/summary`

function GroupsSection({ currentStockCode }: { currentStockCode: string | null }) {
  const groups = useGroups()
  const items = groups.data?.items ?? []
  const [picked, setPicked] = useState<string | null>(() => readPref(PREF.group))
  const selected = items.find(g => String(g.id) === picked) ?? items.find(g => g.kind === "watch") ?? items[0] ?? null
  const detail = useGroup(selected?.id ?? null)
  const pick = (v: string) => { if (!v) return; setPicked(v); writePref(PREF.group, v) }

  return (
    <SidebarGroup>
      <SidebarGroupLabel className="justify-between">
        종목 묶음
        <Link to="/follow/stocks" className="font-normal text-muted-foreground hover:text-foreground">관리</Link>
      </SidebarGroupLabel>
      <SidebarGroupContent>
        {groups.isPending ? <SidebarMenu>{[0, 1, 2].map(i => <SidebarMenuItem key={i}><SidebarMenuSkeleton /></SidebarMenuItem>)}</SidebarMenu>
          : groups.isError ? <Retry onRetry={() => void groups.refetch()} />
          : !items.length ? <p className="px-2 py-1 text-xs text-muted-foreground">종목 묶음을 만들면 여기 보입니다. <Link to="/follow/stocks" className="text-primary hover:underline">묶음 만들기</Link></p>
          : <>
            <ToggleGroup type="single" size="sm" value={selected ? String(selected.id) : ""} onValueChange={pick}
              className="mb-1 flex flex-wrap justify-start gap-1 px-1" aria-label="묶음 선택">
              {items.map(g => (
                <ToggleGroupItem key={g.id} value={String(g.id)} className="h-6 rounded-full border px-2.5 text-xs">
                  {g.name}<span className="ml-1 tabular-nums text-muted-foreground">{g.member_count}</span>
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            {detail.isPending ? <SidebarMenu>{[0, 1, 2].map(i => <SidebarMenuItem key={i}><SidebarMenuSkeleton /></SidebarMenuItem>)}</SidebarMenu>
              : detail.isError ? <Retry onRetry={() => void detail.refetch()} />
              : !detail.data?.members.length ? <p className="px-2 py-1 text-xs text-muted-foreground">이 묶음에 종목이 없습니다.</p>
              : <SidebarMenu>
                {detail.data.members.map(m => (
                  <SidebarMenuItem key={m.stock_code}>
                    <SidebarMenuButton asChild isActive={m.stock_code === currentStockCode} size="sm">
                      <Link to={dossierPath(m.stock_code, m.market)} className="justify-between">
                        <span className="truncate">{m.name}</span>
                        <span className={cn("shrink-0 tabular-nums text-xs",
                          m.change_pct == null ? "text-muted-foreground" : m.change_pct > 0 ? "text-up" : m.change_pct < 0 ? "text-down" : "text-muted-foreground")}>
                          {formatPercent(m.change_pct)}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>}
          </>}
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

function RecentSection({ currentStockCode }: { currentStockCode: string | null }) {
  const recent = readRecentStocks().slice(0, 6)
  if (!recent.length) return null
  return (
    <SidebarGroup>
      <SidebarGroupLabel>최근 본 종목</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {recent.map(r => (
            <SidebarMenuItem key={`${r.market}:${r.code}`}>
              <SidebarMenuButton asChild size="sm" isActive={r.code === currentStockCode}>
                <Link to={r.market === "us" ? `/us/${r.code}` : `/analyze/${r.code}/summary`}><span className="truncate">{r.name}</span></Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

function PeopleSection() {
  const { data, isError, refetch } = useQuery(
    apiQuery<{ entity_id: number; type: string; name: string }[]>({ key: ["spine", "follows"], url: "/api/spine/follows", staleTime: 60_000 }),
  )
  const people = (data ?? []).filter(f => f.type === "person")
  if (isError) return <SidebarGroup><SidebarGroupLabel>팔로우 인물</SidebarGroupLabel><Retry onRetry={() => void refetch()} /></SidebarGroup>
  if (!people.length) return null
  return (
    <SidebarGroup>
      <SidebarGroupLabel className="justify-between">
        팔로우 인물
        <Link to="/people" className="font-normal text-muted-foreground hover:text-foreground">전체</Link>
      </SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {people.slice(0, 8).map(p => (
            <SidebarMenuItem key={p.entity_id}>
              <SidebarMenuButton asChild size="sm"><Link to={`/person?name=${encodeURIComponent(p.name)}`}><span className="truncate">{p.name}</span></Link></SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

function SavedSection() {
  const { data: items = [] } = useSaved()
  return (
    <SidebarGroup>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton asChild size="sm">
            <Link to="/follow/saved" className="justify-between"><span>저장됨</span><span className="tabular-nums text-xs text-muted-foreground">{items.length}</span></Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  )
}

function Retry({ onRetry }: { onRetry: () => void }) {
  return <div className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground">불러오지 못했습니다
    <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onRetry}>다시 시도</Button></div>
}

