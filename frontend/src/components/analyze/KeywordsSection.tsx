import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, X } from "lucide-react"
import api from "@/api/client"
import { toast } from "sonner"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

/* 매칭 키워드 (이 종목을 무엇으로 잡는가) — 언급 탭에서 추출, 종목 홈에서 재사용 */

export function useStockKeywords(stockCode: string) {
  return useQuery({
    queryKey: ["spine", "keywords", stockCode],
    queryFn: async () =>
      (await api.get("/api/spine/keywords", { params: { stock: stockCode } })).data as {
        official_name: string | null
        keywords: { id: number; keyword: string; status: string }[]
      },
    staleTime: 60_000,
  })
}

export default function KeywordsSection({ stockCode, plain = false }: { stockCode: string; plain?: boolean }) {
  const qc = useQueryClient()
  const [input, setInput] = useState("")
  const { data } = useStockKeywords(stockCode)
  const add = useMutation({
    mutationFn: async (keyword: string) =>
      (await api.post("/api/spine/keywords", { stock: stockCode, keyword })).data as { retro_linked_docs: number },
    onSuccess: (d) => {
      toast.success(`키워드 등록 — 기존 문서 ${d.retro_linked_docs}건에 소급 적용`)
      qc.invalidateQueries({ queryKey: ["spine", "keywords", stockCode] })
      qc.invalidateQueries({ queryKey: ["spine", "feed"] })
    },
  })
  const remove = useMutation({
    mutationFn: async (id: number) => api.delete(`/api/spine/keywords/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spine", "keywords", stockCode] }),
  })
  const approve = useMutation({
    mutationFn: async (id: number) =>
      (await api.post(`/api/spine/keywords/${id}/approve`)).data as { keyword: string; retro_linked_docs: number },
    onSuccess: (d) => {
      toast.success(`'${d.keyword}' 승인 — 기존 문서 ${d.retro_linked_docs}건 소급 링크`)
      qc.invalidateQueries({ queryKey: ["spine", "keywords", stockCode] })
      qc.invalidateQueries({ queryKey: ["spine", "feed"] })
    },
  })

  const body = (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary" className="text-[10px]">{data?.official_name ?? "…"} (정식명)</Badge>
        <Badge variant="secondary" className="text-[10px]">{stockCode} (코드)</Badge>
        <Badge variant="outline" className="text-[10px] text-hypothesis border-hypothesis/40">
          + LLM 별칭 자동 인식
        </Badge>
        {(data?.keywords ?? []).filter((k) => k.status !== "proposed").map((k) => (
          <Badge key={k.id} variant="outline" className="text-[10px] gap-1 pr-1">
            {k.keyword}
            <Button variant="ghost" size="sm" className="h-auto p-0" onClick={() => remove.mutate(k.id)} aria-label="키워드 삭제">
              <X className="size-2.5" />
            </Button>
          </Badge>
        ))}
        {/* LLM 자동 제안 별칭 — 승인 시 결정적 매칭 편입 + 소급 링크 */}
        {(data?.keywords ?? []).filter((k) => k.status === "proposed").map((k) => (
          <Badge key={k.id} variant="outline"
            className="text-[10px] gap-1 pr-1 text-hypothesis border-hypothesis/40 bg-hypothesis/5">
            제안: {k.keyword}
            <Button variant="ghost" size="sm" className="h-auto p-0" onClick={() => approve.mutate(k.id)} aria-label="별칭 승인" title="승인 (소급 링크)">
              <Check className="size-2.5" />
            </Button>
            <Button variant="ghost" size="sm" className="h-auto p-0" onClick={() => remove.mutate(k.id)} aria-label="별칭 거부" title="거부">
              <X className="size-2.5" />
            </Button>
          </Badge>
        ))}
      </div>
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (input.trim()) { add.mutate(input.trim()); setInput("") }
        }}
      >
        <Input value={input} onChange={(e) => setInput(e.target.value)}
          placeholder="키워드 추가 (예: 슼하, SKH)" className="h-7 text-xs max-w-[220px]" />
        <Button type="submit" size="xs" variant="outline" disabled={add.isPending}>추가</Button>
        <span className="text-[10px] text-muted-foreground">등록 즉시 소급 적용</span>
      </form>
    </div>
  )

  if (plain) return body

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">매칭 기준</CardTitle>
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  )
}
