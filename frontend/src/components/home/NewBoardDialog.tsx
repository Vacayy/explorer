import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { presetEntries } from "@/components/home/Dashboard"
import { SYSTEM_PRESETS } from "@/components/widgets/registry"
import { useHomeBoards, type HomeBoard } from "@/hooks/useDashboard"

const EMPTY = "empty"

/**
 * 새 홈 메뉴 — 빈 메뉴·시스템 프리셋에서 시작하거나(기본), 지금 메뉴를 복제한다(duplicateOf).
 * 만들면 그 메뉴로 옮겨 간다. 시스템 프리셋은 출발점일 뿐, 만든 뒤엔 그 메뉴의 배치다(home-widgets.md §5).
 */
export function NewBoardDialog({ open, onOpenChange, duplicateOf }: { open: boolean; onOpenChange: (v: boolean) => void; duplicateOf?: HomeBoard }) {
  const boards = useHomeBoards()
  const navigate = useNavigate()
  const [start, setStart] = useState<string>(EMPTY)
  const [name, setName] = useState("")
  const [touched, setTouched] = useState(false)     // 이름을 직접 쳤으면 프리셋을 골라도 덮지 않는다

  const reset = (v: boolean) => {
    if (v) { setStart(EMPTY); setName(duplicateOf ? `${duplicateOf.label} 사본`.slice(0, 30) : ""); setTouched(false) }
    onOpenChange(v)
  }
  const pick = (key: string) => {
    if (!key) return
    setStart(key)
    if (!touched) setName(SYSTEM_PRESETS.find(p => p.key === key)?.label ?? "")
  }
  const submit = () => {
    const label = name.trim()
    if (!label) return
    const preset = SYSTEM_PRESETS.find(p => p.key === start)
    const items = duplicateOf ? duplicateOf.items : preset ? presetEntries(preset.widgets) : []
    boards.create.mutate({ label, items }, {
      onSuccess: b => { toast.success(`'${b.label}' 메뉴를 만들었어요.`); navigate(`/home/b/${b.id}`) },
      onError: () => toast.error("메뉴를 만들지 못했습니다."),
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{duplicateOf ? `'${duplicateOf.label}' 복제` : "새 메뉴"}</DialogTitle>
          <DialogDescription>
            {duplicateOf ? "지금 메뉴의 위젯과 배치(종목 추적 위젯의 종목 포함)를 그대로 가진 새 메뉴를 만들어요." : "빈 메뉴나 시스템 프리셋에서 시작해, 위젯을 더하고 옮겨 나만의 메뉴로 만드세요."}
          </DialogDescription>
        </DialogHeader>
        {!duplicateOf && (
          <ToggleGroup type="single" spacing={2} value={start} onValueChange={pick} className="grid w-full grid-cols-2 items-stretch">
            {[{ key: EMPTY, label: "빈 메뉴", description: "위젯 없이 시작" }, ...SYSTEM_PRESETS].map(p => (
              <ToggleGroupItem key={p.key} value={p.key}
                className="h-auto flex-col items-start justify-start gap-0.5 rounded-lg border px-3 py-2 text-left data-[state=on]:border-primary data-[state=on]:bg-primary/5">
                <span className="text-sm font-medium">{p.label}</span>
                <span className="text-xs font-normal whitespace-normal text-muted-foreground">{p.description}</span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
        <Input autoFocus={!!duplicateOf} value={name} maxLength={30} placeholder="메뉴 이름 (예: 아침 점검, 종목 추적)"
          onChange={e => { setName(e.target.value); setTouched(true) }} onKeyDown={e => { if (e.key === "Enter") submit() }} />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>취소</Button>
          <Button disabled={!name.trim() || boards.create.isPending} onClick={submit}>만들기</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
