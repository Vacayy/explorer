import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { ChevronDown } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, STALE } from "@/api/query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Markdown } from "@/components/shared/Markdown"
import { cn } from "@/lib/utils"

/**
 * 메가 내러티브 — 공유노드 군집을 관통하는 상위 세계관 서사 (D-031/D-032).
 * 온톨로지(그래프)의 '읽기'에 해당 — 내러티브 랜딩에서 지식 탭으로 이관(D-056).
 */
interface MegaNarrative {
  id: number; name: string; title: string | null; narrative: string | null
  members: string[]; version: number; created_at: string | null
}

export function MegaNarrativeSection() {
  const navigate = useNavigate()
  const [openId, setOpenId] = useState<number | null>(null)
  const { data } = useQuery(
    apiQuery<MegaNarrative[]>({
      key: ["spine", "narrative", "mega"],
      url: "/api/spine/narrative/mega",
      staleTime: STALE.medium,
    }),
  )
  const items = data ?? []
  if (items.length === 0) return null

  return (
    <div className="space-y-2.5">
      {items.map((m) => (
        <Card key={m.id} className="bg-[color-mix(in_srgb,var(--primary)_5%,var(--card))]">
          <CardContent className="py-3 space-y-2">
            <Collapsible open={openId === m.id} onOpenChange={(o) => setOpenId(o ? m.id : null)}>
              <CollapsibleTrigger asChild>
                <button className="w-full text-left group">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge className="text-[10px]">세계관</Badge>
                    <span className="font-semibold text-sm group-hover:underline">{m.title ?? m.name}</span>
                    {m.version > 1 && (
                      <Badge variant="outline" className="text-[10px] text-muted-foreground">v{m.version}</Badge>
                    )}
                    <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground ml-auto transition-transform shrink-0",
                      openId === m.id && "rotate-180")} />
                  </div>
                  <div className="flex items-center gap-1 flex-wrap mt-1.5">
                    <span className="text-[10px] text-muted-foreground mr-0.5">{m.members.length}개 서사를 관통 —</span>
                    {m.members.map((t) => (
                      <Badge key={t} variant="secondary" className="text-[10px] cursor-pointer hover:bg-accent"
                        onClick={(e) => { e.stopPropagation(); navigate(`/narrative?topic=${encodeURIComponent(t)}`) }}>
                        {t}
                      </Badge>
                    ))}
                  </div>
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                {m.narrative && (
                  <div className="pt-2">
                    <Markdown>{m.narrative}</Markdown>
                    <div className="text-right mt-2">
                      <Badge variant="outline" className="text-[9px] font-normal text-hypothesis border-hypothesis/40">
                        AI 세계관 서사 · 부분 서사 변경 시 갱신 — 검증 필요
                        {m.created_at && ` · ${m.created_at.slice(0, 10)}`}
                      </Badge>
                    </div>
                  </div>
                )}
              </CollapsibleContent>
            </Collapsible>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
