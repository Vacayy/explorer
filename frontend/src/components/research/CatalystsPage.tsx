import { useState } from "react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { useCatalysts, useCreateCatalyst, useDeleteCatalyst } from "@/hooks/useCatalysts"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import CompanySearchCombobox from "@/components/shared/CompanySearchCombobox"
import type { CatalystItem } from "@/types"
import type { Company } from "@/types"

const EVENT_TYPES = [
  { value: "earnings", label: "실적발표", icon: "📊" },
  { value: "filing", label: "공시", icon: "📋" },
  { value: "contract", label: "계약", icon: "📝" },
  { value: "capex", label: "설비투자", icon: "🏭" },
  { value: "regulation", label: "규제", icon: "⚖️" },
  { value: "other", label: "기타", icon: "📌" },
]

const PERIOD_OPTIONS = [
  { value: 30, label: "30일" },
  { value: 90, label: "90일" },
  { value: 180, label: "180일" },
]

function eventTypeInfo(type: string) {
  return EVENT_TYPES.find((t) => t.value === type) ?? { icon: "📌", label: type }
}

function groupByMonth(items: CatalystItem[]): Map<string, CatalystItem[]> {
  const map = new Map<string, CatalystItem[]>()
  for (const item of items) {
    const key = item.event_date.slice(0, 7) // "YYYY-MM"
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(item)
  }
  return map
}

function monthLabel(key: string): string {
  const [year, month] = key.split("-")
  return `${year}년 ${parseInt(month)}월`
}

export default function CatalystsPage() {
  const [days, setDays] = useState(90)
  const [showAddForm, setShowAddForm] = useState(false)
  const [showPast, setShowPast] = useState(false)

  // Add form state
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null)
  const [eventType, setEventType] = useState("earnings")
  const [eventDate, setEventDate] = useState("")
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")

  const { data: items = [], isLoading } = useCatalysts(days)
  const createCatalyst = useCreateCatalyst()
  const deleteCatalyst = useDeleteCatalyst()

  const today = new Date().toISOString().slice(0, 10)
  const pastItems = items.filter((i) => i.event_date < today)
  const upcomingItems = items.filter((i) => i.event_date >= today)

  const upcomingGroups = groupByMonth(upcomingItems)
  const pastGroups = groupByMonth(pastItems)

  const handleAdd = async () => {
    if (!title || !eventDate) return
    await createCatalyst.mutateAsync({
      stock_code: selectedCompany?.stock_code ?? null,
      event_type: eventType,
      event_date: eventDate,
      title,
      description: description || null,
    })
    toast.success("이벤트가 추가되었습니다")
    setShowAddForm(false)
    setSelectedCompany(null)
    setEventType("earnings")
    setEventDate("")
    setTitle("")
    setDescription("")
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">카탈리스트</h1>
        <Button size="sm" onClick={() => setShowAddForm((v) => !v)}>
          + 이벤트 추가
        </Button>
      </div>

      {/* Add form */}
      {showAddForm && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            {/* Company search (optional) */}
            <CompanySearchCombobox
              value={selectedCompany}
              onSelect={setSelectedCompany}
              placeholder="종목명 검색 (선택, 시장 이벤트는 비워두세요)"
              className="w-full"
            />

            {/* Event type */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-16 shrink-0">유형</span>
              <Select value={eventType} onValueChange={setEventType}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EVENT_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.icon} {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Date */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-16 shrink-0">날짜</span>
              <Input
                type="date"
                className="max-w-[180px]"
                value={eventDate}
                onChange={(e) => setEventDate(e.target.value)}
              />
            </div>

            {/* Title */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-16 shrink-0">제목</span>
              <Input
                placeholder="이벤트 제목"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>

            {/* Description */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground w-16 shrink-0">메모</span>
              <Input
                placeholder="추가 설명 (선택)"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" onClick={() => setShowAddForm(false)}>
                취소
              </Button>
              <Button
                size="sm"
                onClick={handleAdd}
                disabled={!title || !eventDate || createCatalyst.isPending}
              >
                {createCatalyst.isPending ? "추가 중..." : "추가"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Period filter */}
      <div className="flex gap-2 items-center">
        <span className="text-xs text-muted-foreground">기간:</span>
        {PERIOD_OPTIONS.map((p) => (
          <Button
            key={p.value}
            variant="outline"
            size="xs"
            onClick={() => setDays(p.value)}
            className={cn(
              days === p.value
                ? "border-primary text-primary bg-primary/5"
                : "border-border text-muted-foreground hover:text-foreground"
            )}
          >
            {p.label}
          </Button>
        ))}
      </div>

      {/* Content */}
      {isLoading ? (
        <p className="text-muted-foreground text-sm py-8 text-center">로딩 중...</p>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground space-y-3">
          <p>예정된 이벤트가 없습니다</p>
          <Button size="sm" variant="outline" onClick={() => setShowAddForm(true)}>
            + 이벤트 추가
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Upcoming events grouped by month */}
          {upcomingItems.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              예정된 이벤트가 없습니다
            </p>
          ) : (
            Array.from(upcomingGroups.entries()).map(([month, monthItems]) => (
              <div key={month} className="space-y-2">
                <h2 className="text-sm font-semibold text-muted-foreground flex items-center gap-1">
                  📅 {monthLabel(month)}
                </h2>
                <div className="space-y-1">
                  {monthItems.map((item) => (
                    <EventRow
                      key={item.id}
                      item={item}
                      onDelete={() => deleteCatalyst.mutate(item.id, { onSuccess: () => toast.success("삭제되었습니다") })}
                      isDeleting={deleteCatalyst.isPending}
                    />
                  ))}
                </div>
              </div>
            ))
          )}

          {/* Past events (collapsed by default) */}
          {pastItems.length > 0 && (
            <div className="space-y-2">
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors px-0"
                onClick={() => setShowPast((v) => !v)}
              >
                {showPast ? "▼" : "▶"} 지난 이벤트 ({pastItems.length})
              </Button>
              {showPast && (
                <div className="space-y-4 opacity-60">
                  {Array.from(pastGroups.entries()).map(([month, monthItems]) => (
                    <div key={month} className="space-y-2">
                      <h2 className="text-sm font-semibold text-muted-foreground flex items-center gap-1">
                        📅 {monthLabel(month)}
                      </h2>
                      <div className="space-y-1">
                        {monthItems.map((item) => (
                          <EventRow
                            key={item.id}
                            item={item}
                            onDelete={() => deleteCatalyst.mutate(item.id, { onSuccess: () => toast.success("삭제되었습니다") })}
                            isDeleting={deleteCatalyst.isPending}
                            past
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function EventRow({
  item,
  onDelete,
  isDeleting,
  past = false,
}: {
  item: CatalystItem
  onDelete: () => void
  isDeleting: boolean
  past?: boolean
}) {
  const { icon } = eventTypeInfo(item.event_type)
  const day = item.event_date.slice(8, 10)

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-lg border bg-card hover:bg-accent/30 transition-colors group",
        past && "text-muted-foreground"
      )}
    >
      {/* Day */}
      <span className="font-mono text-sm font-medium w-6 shrink-0 text-center">{day}</span>

      {/* Icon */}
      <span className="text-base shrink-0">{icon}</span>

      {/* Corp name badge */}
      {item.corp_name && (
        <Badge variant="outline" className="text-xs shrink-0">
          {item.corp_name}
        </Badge>
      )}

      {/* Title */}
      <span className="text-sm flex-1 truncate">{item.title}</span>

      {/* Description */}
      {item.description && (
        <span className="text-xs text-muted-foreground truncate max-w-[200px] hidden md:block">
          {item.description}
        </span>
      )}

      {/* Delete */}
      <Button
        variant="ghost"
        size="sm"
        className="h-6 px-2 text-[11px] text-muted-foreground hover:text-rose-600 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
        onClick={onDelete}
        disabled={isDeleting}
      >
        삭제
      </Button>
    </div>
  )
}
