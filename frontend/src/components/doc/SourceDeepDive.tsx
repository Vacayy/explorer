import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { toast } from "sonner"
import { Loader2, Sparkles, Telescope } from "lucide-react"
import api from "@/api/client"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Markdown } from "@/components/shared/Markdown"
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
interface ScenarioResult { answer: string; beneficiaries: { name?: string; reason?: string }[] }

export function SourceDeepDive({ docId }: { docId: number }) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)
  const navigate = useNavigate()

  const derive = useMutation({
    mutationFn: async () => (await api.post("/api/spine/questions/from-doc", { doc_id: docId })).data as DeriveResult,
    onError: () => toast.error("질문 도출 실패 — 다시 시도"),
  })
  const track = useMutation({
    mutationFn: async (text: string) =>
      (await api.post("/api/spine/questions", { text, source_doc_id: docId })).data,
    onSuccess: () => { toast.success("질문 추적 시작 — 지식 탭에서 확인"); setOpen(false); navigate("/knowledge") },
    onError: () => toast.error("분해 실패 — 다시 시도"),
  })
  const scenario = useMutation({
    mutationFn: async (event: string) =>
      (await api.post("/api/spine/questions/scenario", { event })).data as ScenarioResult,
    onError: () => toast.error("시나리오 생성 실패"),
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
            이 소스가 던지는 핵심질문을 뽑아 추적하고, 파급 시나리오도 함께 봅니다 — corpus 누적을 기다리지 않고.
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
              <p className="text-[11px] font-medium text-muted-foreground mb-1.5">딥다이브 핵심질문 후보 — 하나 골라 추적</p>
              <div className="space-y-1.5">
                {d.candidates.map((c) => (
                  <button key={c} onClick={() => setPicked(c)}
                    className={cn("w-full text-left rounded-md border px-3 py-2 text-sm transition-colors",
                      picked === c ? "border-primary bg-primary/5" : "hover:border-primary/50")}>
                    {c}
                  </button>
                ))}
              </div>
              <Button size="sm" className="mt-2 w-full" disabled={!picked || track.isPending}
                onClick={() => picked && track.mutate(picked)}>
                {track.isPending
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 분해·추적 시작 중… (수 분)</>
                  : <><Sparkles className="h-3.5 w-3.5" /> 질문으로 추적</>}
              </Button>
            </div>

            {d.event && (
              <div className="border-t pt-3">
                <p className="text-[11px] font-medium text-muted-foreground mb-1">파급 사건</p>
                <p className="text-sm mb-2">{d.event}</p>
                {!scenario.data && (
                  <Button size="sm" variant="outline" className="w-full" disabled={scenario.isPending}
                    onClick={() => scenario.mutate(d.event)}>
                    {scenario.isPending
                      ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 파급 시나리오 전개 중… (수 분)</>
                      : <>파급 시나리오 생성</>}
                  </Button>
                )}
                {scenario.data && (
                  <div className="rounded-md border bg-muted/30 px-3 py-2 mt-1">
                    <Markdown>{scenario.data.answer}</Markdown>
                    {scenario.data.beneficiaries.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t">
                        <span className="text-[10px] text-muted-foreground mr-1">논리상 수혜:</span>
                        {scenario.data.beneficiaries.map((b, i) => (
                          <Badge key={i} variant="outline" className="text-[10px]" title={b.reason ?? ""}>
                            {b.name ?? "?"}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
