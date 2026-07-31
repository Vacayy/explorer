import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { toast } from "sonner"
import { Check, Loader2, Sparkles, Telescope } from "lucide-react"
import api from "@/api/client"
import { Button } from "@/components/ui/button"
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

/**
 * Q5 (D-067, docs/specs/question-proxy.md) — 단일 소스 딥다이브.
 * 이 문서를 소스로 딥다이브 핵심질문 후보를 도출(sonnet)하고, 픽하면 질문 트래커로 추적 +
 * 도출된 파급 event로 시나리오도 함께. corpus 누적 없이 "이 소스 하나가 중요하다"를 선언.
 */

interface DeriveResult { doc_id: number; title: string | null; candidates: string[]; event: string }

export function SourceDeepDive({ docId }: { docId: number }) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const navigate = useNavigate()

  const derive = useMutation({
    mutationFn: async () => (await api.post("/api/spine/questions/from-doc", { doc_id: docId })).data as DeriveResult,
    onError: () => toast.error("질문 도출 실패 — 다시 시도"),
  })
  const track = useMutation({
    mutationFn: async (texts: string[]) => Promise.all(
      texts.map((text) =>
        api.post("/api/spine/questions", { text, source_doc_id: docId }).then((r) => r.data as { id: number }))),
    onSuccess: (qs) => {
      toast.success(`${qs.length}개 질문 추적 시작`)
      setOpen(false)
      navigate(qs.length === 1 ? `/question/${qs[0].id}` : "/questions")
    },
    onError: () => toast.error("분해 실패 — 다시 시도"),
  })

  const toggle = (c: string) => setPicked((prev) => {
    const next = new Set(prev)
    next.has(c) ? next.delete(c) : next.add(c)
    return next
  })

  const onOpenChange = (o: boolean) => {
    setOpen(o)
    if (o && !derive.data && !derive.isPending) derive.mutate()
  }
  const d = derive.data

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="text-hypothesis border-hypothesis/40 hover:bg-hypothesis/5">
          <Telescope className="h-3.5 w-3.5" /> 이 소스로 파보기
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-1.5 text-base">
            <Telescope className="h-4 w-4 text-hypothesis" /> 단일 소스 딥다이브
          </DialogTitle>
          <DialogDescription>
            이 소스가 던지는 핵심질문을 뽑아 추적하고, 파급 시나리오도 함께 봅니다
          </DialogDescription>
        </DialogHeader>

        {derive.isPending && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" /> 소스를 읽고 핵심질문을 도출하는 중… (수십 초)
          </div>
        )}

        {d && (
          <div className="space-y-3">
            <div>
              <p className="text-[11px] font-medium text-muted-foreground mb-1.5">딥다이브 핵심질문 후보 — 추적할 질문을 고르세요 (복수 선택)</p>
              <div className="space-y-1.5">
                {d.candidates.map((c) => {
                  const on = picked.has(c)
                  return (
                    <button key={c} onClick={() => toggle(c)}
                      className={cn("w-full flex items-start gap-2 text-left rounded-md border px-3 py-2 text-sm transition-colors",
                        on ? "border-primary bg-primary/5" : "hover:border-primary/50")}>
                      <span className={cn("mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                        on ? "bg-primary border-primary text-primary-foreground" : "border-muted-foreground/40")}>
                        {on && <Check className="h-3 w-3" />}
                      </span>
                      <span className="min-w-0 flex-1">{c}</span>
                    </button>
                  )
                })}
              </div>
              <Button size="sm" className="mt-2 w-full" disabled={picked.size === 0 || track.isPending}
                onClick={() => track.mutate([...picked])}>
                {track.isPending
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> {picked.size}개 분해·추적 시작 중… (수 분)</>
                  : <><Sparkles className="h-3.5 w-3.5" /> 질문으로 추적{picked.size > 0 ? ` (${picked.size})` : ""}</>}
              </Button>
            </div>

            {d.event && (
              <div className="border-t pt-3">
                <p className="text-[11px] font-medium text-muted-foreground mb-1">파급 사건 (질문 추적 시작 후 상세에서 시나리오 생성)</p>
                <p className="text-sm text-muted-foreground">{d.event}</p>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
