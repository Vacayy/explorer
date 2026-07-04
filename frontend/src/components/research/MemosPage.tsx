import { useState, useRef, useEffect } from "react"
import { toast } from "sonner"
import { useWatchlist } from "@/hooks/useWatchlist"
import { useIRNotes, useCreateIRNote, useDeleteIRNote, useUpdateIRNote } from "@/hooks/useIRNotes"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent } from "@/components/ui/card"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/shared/Skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { cn } from "@/lib/utils"
import type { IRNote } from "@/types"

// ─── Section config ────────────────────────────────────────────────────────────

type SectionKey = "bull" | "bear" | "catalyst" | "risk"

interface SectionConfig {
  key: SectionKey
  label: string
  emoji: string
  bg: string
  border: string
  text: string
}

const SECTIONS: SectionConfig[] = [
  {
    key: "bull",
    label: "Bull Thesis",
    emoji: "🟢",
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    text: "text-emerald-700",
  },
  {
    key: "bear",
    label: "Bear Thesis",
    emoji: "🔴",
    bg: "bg-rose-50",
    border: "border-rose-200",
    text: "text-rose-700",
  },
  {
    key: "catalyst",
    label: "Catalysts",
    emoji: "📋",
    bg: "bg-blue-50",
    border: "border-blue-200",
    text: "text-blue-700",
  },
  {
    key: "risk",
    label: "Risks",
    emoji: "⚠️",
    bg: "bg-amber-50",
    border: "border-amber-200",
    text: "text-amber-700",
  },
]

// ─── Inline editable item ──────────────────────────────────────────────────────

interface ThesisItemProps {
  note: IRNote
  onDelete: (id: number) => void
  onEdit: (id: number, title: string) => void
}

function ThesisItem({ note, onDelete, onEdit }: ThesisItemProps) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(note.title)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const handleSave = () => {
    const trimmed = value.trim()
    if (trimmed && trimmed !== note.title) {
      onEdit(note.id, trimmed)
    }
    setEditing(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSave()
    if (e.key === "Escape") { setValue(note.title); setEditing(false) }
  }

  return (
    <div className="group flex items-center gap-2 py-1">
      <span className="text-muted-foreground text-xs mt-px shrink-0">•</span>
      {editing ? (
        <Input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={handleSave}
          onKeyDown={handleKeyDown}
          className="h-6 text-sm py-0 px-1 flex-1"
        />
      ) : (
        <span
          className="text-sm flex-1 cursor-pointer hover:text-foreground/80"
          onClick={() => setEditing(true)}
        >
          {note.title}
        </span>
      )}
      <Button
        variant="ghost"
        size="icon-xs"
        className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity shrink-0"
        onClick={() => onDelete(note.id)}
        aria-label="삭제"
      >
        ✕
      </Button>
    </div>
  )
}

// ─── Single thesis section ─────────────────────────────────────────────────────

interface ThesisSectionProps {
  config: SectionConfig
  notes: IRNote[]
  stockCode: string
}

function ThesisSection({ config, notes, stockCode }: ThesisSectionProps) {
  const [adding, setAdding] = useState(false)
  const [inputValue, setInputValue] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  const createNote = useCreateIRNote(stockCode)
  const deleteNote = useDeleteIRNote(stockCode)
  const updateNote = useUpdateIRNote(stockCode)

  useEffect(() => {
    if (adding) inputRef.current?.focus()
  }, [adding])

  const handleAdd = () => {
    const title = inputValue.trim()
    if (!title) { setAdding(false); return }
    createNote.mutate(
      {
        title,
        note_date: new Date().toISOString().slice(0, 10),
        memo_type: config.key,
      },
      {
        onSuccess: () => {
          setInputValue("")
          setAdding(false)
          toast.success("저장되었습니다")
        },
      }
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleAdd()
    if (e.key === "Escape") { setInputValue(""); setAdding(false) }
  }

  return (
    <div className={cn("rounded-lg border p-4 flex flex-col gap-2 min-h-[140px]", config.bg, config.border)}>
      <div className={cn("flex items-center gap-1.5 font-semibold text-sm mb-1", config.text)}>
        <span>{config.emoji}</span>
        <span>{config.label}</span>
      </div>

      <div className="flex-1 space-y-0.5">
        {notes.map((note) => (
          <ThesisItem
            key={note.id}
            note={note}
            onDelete={(id) => deleteNote.mutate(id, { onSuccess: () => toast.success("삭제되었습니다") })}
            onEdit={(id, title) => updateNote.mutate({ id, title })}
          />
        ))}
      </div>

      {adding ? (
        <div className="flex gap-1 mt-1">
          <Input
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={handleAdd}
            placeholder="내용 입력 후 Enter"
            className="h-7 text-sm py-0 flex-1"
          />
        </div>
      ) : (
        <Button
          variant="ghost"
          size="xs"
          className={cn("mt-1 justify-start hover:underline", config.text)}
          onClick={() => setAdding(true)}
        >
          + 추가
        </Button>
      )}
    </div>
  )
}

// ─── Structured view (투자논점) ────────────────────────────────────────────────

interface StructuredViewProps {
  stockCode: string
}

function StructuredView({ stockCode }: StructuredViewProps) {
  const bull = useIRNotes(stockCode, "bull")
  const bear = useIRNotes(stockCode, "bear")
  const catalyst = useIRNotes(stockCode, "catalyst")
  const risk = useIRNotes(stockCode, "risk")

  const isLoading = bull.isLoading || bear.isLoading || catalyst.isLoading || risk.isLoading
  const isError = bull.isError || bear.isError || catalyst.isError || risk.isError

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-36 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        message="투자 논점을 불러올 수 없습니다."
        onRetry={() => { bull.refetch(); bear.refetch(); catalyst.refetch(); risk.refetch() }}
      />
    )
  }

  const notesByKey: Record<SectionKey, IRNote[]> = {
    bull: bull.data ?? [],
    bear: bear.data ?? [],
    catalyst: catalyst.data ?? [],
    risk: risk.data ?? [],
  }

  return (
    <div className="grid grid-cols-2 gap-4">
      {SECTIONS.map((section) => (
        <ThesisSection
          key={section.key}
          config={section}
          notes={notesByKey[section.key]}
          stockCode={stockCode}
        />
      ))}
    </div>
  )
}

// ─── General memo (자유메모) ────────────────────────────────────────────────────

interface GeneralMemosProps {
  stockCode: string
}

function GeneralMemos({ stockCode }: GeneralMemosProps) {
  const { data: notes = [], isLoading, isError, refetch } = useIRNotes(stockCode, "general")
  const createNote = useCreateIRNote(stockCode)
  const deleteNote = useDeleteIRNote(stockCode)

  const [showForm, setShowForm] = useState(false)
  const [noteTitle, setNoteTitle] = useState("")
  const [noteContent, setNoteContent] = useState("")
  const [noteDate, setNoteDate] = useState(new Date().toISOString().slice(0, 10))

  const handleCreate = () => {
    if (!noteTitle.trim()) return
    createNote.mutate(
      { title: noteTitle, content: noteContent, note_date: noteDate, memo_type: "general" },
      {
        onSuccess: () => {
          setNoteTitle("")
          setNoteContent("")
          setNoteDate(new Date().toISOString().slice(0, 10))
          setShowForm(false)
          toast.success("저장되었습니다")
        },
      }
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return <ErrorState message="메모를 불러올 수 없습니다." onRetry={refetch} />
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">자유메모</h3>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          {showForm ? "취소" : "+ 새 메모"}
        </Button>
      </div>

      {showForm && (
        <Card>
          <CardContent className="pt-5 space-y-3">
            <div className="flex gap-3">
              <Input
                type="date"
                value={noteDate}
                onChange={(e) => setNoteDate(e.target.value)}
                className="w-[160px]"
              />
              <Input
                value={noteTitle}
                onChange={(e) => setNoteTitle(e.target.value)}
                placeholder="제목"
                className="flex-1"
              />
            </div>
            <Textarea
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              placeholder="내용"
              rows={6}
            />
            <Button onClick={handleCreate} disabled={createNote.isPending}>
              저장
            </Button>
          </CardContent>
        </Card>
      )}

      {notes.length === 0 && !showForm && (
        <p className="text-muted-foreground text-center py-10 text-sm">등록된 메모가 없습니다.</p>
      )}

      <div className="space-y-3">
        {notes.map((note) => (
          <Card key={note.id}>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <span className="text-xs text-muted-foreground mr-3">{note.note_date}</span>
                  <span className="font-semibold text-sm">{note.title}</span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive text-xs h-7"
                  onClick={() => {
                    if (confirm("삭제하시겠습니까?")) deleteNote.mutate(note.id, { onSuccess: () => toast.success("삭제되었습니다") })
                  }}
                >
                  삭제
                </Button>
              </div>
              {note.content && (
                <p className="text-sm text-secondary-foreground whitespace-pre-wrap leading-relaxed">
                  {note.content}
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

const SUB_TABS = [
  { key: "thesis" as const, label: "투자논점" },
  { key: "general" as const, label: "자유메모" },
]

export default function MemosPage() {
  const { data: watchlist = [], isLoading: watchlistLoading } = useWatchlist()
  const [selectedStockCode, setSelectedStockCode] = useState<string>("")
  const [activeTab, setActiveTab] = useState<"thesis" | "general">("thesis")

  return (
    <div className="space-y-5">
      {/* Company selector */}
      <div className="flex items-center gap-3">
        <Label className="text-sm font-medium text-muted-foreground whitespace-nowrap">기업 선택</Label>
        {watchlistLoading ? (
          <Skeleton className="h-9 w-48" />
        ) : (
          <Select value={selectedStockCode} onValueChange={setSelectedStockCode}>
            <SelectTrigger className="w-56">
              <SelectValue placeholder="-- 기업을 선택하세요 --" />
            </SelectTrigger>
            <SelectContent>
              {watchlist.map((item) => (
                <SelectItem key={item.stock_code} value={item.stock_code ?? ""}>
                  {item.corp_name} ({item.stock_code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* No company selected */}
      {!selectedStockCode && !watchlistLoading && (
        <div className="py-16 text-center space-y-4">
          <p className="text-muted-foreground text-sm">기업을 선택해주세요</p>
          {watchlist.length > 0 && (
            <div className="flex flex-wrap gap-2 justify-center">
              {watchlist.slice(0, 3).map((item) => (
                <Button
                  key={item.stock_code}
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedStockCode(item.stock_code ?? "")}
                >
                  {item.corp_name}
                </Button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Content */}
      {selectedStockCode && (
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "thesis" | "general")}>
          <TabsList>
            {SUB_TABS.map((t) => (
              <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="thesis">
            <StructuredView stockCode={selectedStockCode} />
          </TabsContent>
          <TabsContent value="general">
            <GeneralMemos stockCode={selectedStockCode} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
