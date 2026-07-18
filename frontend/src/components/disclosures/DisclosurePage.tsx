import { useState } from "react"
import NextQuestions from "@/components/shared/NextQuestions"
import { useDisclosures } from "@/hooks/useDisclosures"
import { useIRNotes, useCreateIRNote, useDeleteIRNote } from "@/hooks/useIRNotes"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { AlertDialog, AlertDialogTrigger, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/components/ui/alert-dialog"
import FilterChips from "@/components/shared/FilterChips"
import { PageContainer } from "@/components/shared/PageContainer"

interface Props {
  stockCode: string
  corpCode: string
}

const KIND_OPTIONS = [
  { value: "", label: "전체" },
  { value: "A", label: "정기공시" },
  { value: "B", label: "주요사항보고" },
  { value: "C", label: "발행공시" },
  { value: "D", label: "지분공시" },
  { value: "E", label: "기타공시" },
]

const SUB_TABS = [
  { key: "disclosure" as const, label: "공시목록" },
  { key: "ir" as const, label: "IR 메모" },
]

export default function DisclosurePage({ stockCode }: Props) {
  const [kind, setKind] = useState("")
  const [page, setPage] = useState(1)
  const [activeTab, setActiveTab] = useState<"disclosure" | "ir">("disclosure")

  const { data: discData, isLoading: discLoading } = useDisclosures(stockCode, kind || undefined, undefined, undefined, page)
  const { data: notes = [], isLoading: notesLoading } = useIRNotes(stockCode)
  const createNote = useCreateIRNote(stockCode)
  const deleteNote = useDeleteIRNote(stockCode)

  const [noteTitle, setNoteTitle] = useState("")
  const [noteContent, setNoteContent] = useState("")
  const [noteDate, setNoteDate] = useState(new Date().toISOString().slice(0, 10))
  const [showForm, setShowForm] = useState(false)

  const handleCreateNote = () => {
    if (!noteTitle.trim()) return
    createNote.mutate(
      { title: noteTitle, content: noteContent, note_date: noteDate },
      { onSuccess: () => { setNoteTitle(""); setNoteContent(""); setShowForm(false) } }
    )
  }

  return (
    <PageContainer>
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "disclosure" | "ir")}>
        <TabsList>
          {SUB_TABS.map((t) => (
            <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="disclosure">
          <div className="space-y-5">
            <FilterChips options={KIND_OPTIONS} value={kind} onChange={(v) => { setKind(v); setPage(1) }} />

          {discLoading && <p className="text-muted-foreground">로딩 중...</p>}

          {discData && (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-center w-[100px]">접수일</TableHead>
                    <TableHead>보고서명</TableHead>
                    <TableHead className="text-center w-[100px]">제출인</TableHead>
                    <TableHead className="text-center w-[60px]">비고</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {discData.items.map((item) => (
                    <TableRow key={item.rcp_no}>
                      <TableCell className="text-center whitespace-nowrap">{item.rcept_dt}</TableCell>
                      <TableCell>
                        {item.dart_url ? (
                          <a href={item.dart_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                            {item.report_nm}
                          </a>
                        ) : item.report_nm}
                      </TableCell>
                      <TableCell className="text-center">{item.flr_nm}</TableCell>
                      <TableCell className="text-center">{item.rm}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <div className="flex items-center justify-center gap-2">
                <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>이전</Button>
                <span className="text-sm text-muted-foreground px-3">{page} / {Math.ceil(discData.total / 20) || 1}</span>
                <Button variant="outline" size="sm" onClick={() => setPage((p) => p + 1)} disabled={discData.items.length < 20}>다음</Button>
              </div>
            </>
          )}
          </div>
        </TabsContent>

        <TabsContent value="ir">
          <div className="space-y-5">
            <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">IR / 컨퍼런스콜 메모</h3>
            <Button size="sm" onClick={() => setShowForm(!showForm)}>
              {showForm ? "취소" : "+ 새 메모"}
            </Button>
          </div>

          {showForm && (
            <Card>
              <CardContent className="pt-5 space-y-3">
                <div className="flex gap-3">
                  <Input type="date" value={noteDate} onChange={(e) => setNoteDate(e.target.value)} className="w-[160px]" />
                  <Input value={noteTitle} onChange={(e) => setNoteTitle(e.target.value)} placeholder="제목" className="flex-1" />
                </div>
                <Textarea value={noteContent} onChange={(e) => setNoteContent(e.target.value)} placeholder="내용" rows={6} />
                <Button onClick={handleCreateNote} disabled={createNote.isPending}>저장</Button>
              </CardContent>
            </Card>
          )}

          {notesLoading && <p className="text-muted-foreground">로딩 중...</p>}

          {notes.length === 0 && !notesLoading && (
            <p className="text-muted-foreground text-center py-10">등록된 메모가 없습니다.</p>
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
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="sm" className="text-destructive text-xs h-7">
                          삭제
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>삭제하시겠습니까?</AlertDialogTitle>
                          <AlertDialogDescription>이 작업은 되돌릴 수 없습니다.</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>취소</AlertDialogCancel>
                          <AlertDialogAction onClick={() => deleteNote.mutate(note.id)}>삭제</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                  {note.content && (
                    <p className="text-sm text-secondary-foreground whitespace-pre-wrap leading-relaxed">{note.content}</p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
          </div>
        </TabsContent>
      </Tabs>
      {/* 다음 질문 — dead-end 제거 (P2-3) */}
      <NextQuestions stockCode={stockCode} context="disclosures" />
    </PageContainer>
  )
}
