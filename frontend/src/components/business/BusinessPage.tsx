import { useState } from "react"
import NextQuestions from "@/components/shared/NextQuestions"
import { useBusinessSegments, useCreateSegment, useDeleteSegment } from "@/hooks/useBusiness"
import ChartCard from "@/components/shared/ChartCard"
import SegmentTabs from "@/components/shared/SegmentTabs"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { formatKrw } from "@/utils/format"
import {
  PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts"

interface Props {
  stockCode: string
  corpCode: string
}

const RAW_COLORS = ["#4472C4", "#ED7D31", "#70AD47", "#dc2626", "#8b5cf6", "#ec4899", "#14b8a6", "#FFC000"]

const SEG_TABS = [
  { value: "division", label: "사업부문" },
  { value: "region", label: "사업지역" },
]

export default function BusinessPage({ stockCode }: Props) {
  const [segType, setSegType] = useState("division")
  const { data, isLoading } = useBusinessSegments(stockCode, segType)
  const createSeg = useCreateSegment(stockCode)
  const deleteSeg = useDeleteSegment(stockCode)

  const [showForm, setShowForm] = useState(false)
  const [formYear, setFormYear] = useState(new Date().getFullYear())
  const [formName, setFormName] = useState("")
  const [formRevenue, setFormRevenue] = useState("")
  const [formRatio, setFormRatio] = useState("")

  const items = data?.items || []
  const byYear: Record<number, typeof items> = {}
  for (const item of items) {
    if (!byYear[item.bsns_year]) byYear[item.bsns_year] = []
    byYear[item.bsns_year].push(item)
  }
  const years = Object.keys(byYear).map(Number).sort()
  const latestYear = years[years.length - 1]
  const latestData = byYear[latestYear] || []

  const pieData = latestData.map((s) => ({ name: s.segment_name, value: s.revenue || 0 }))
  const allSegNames = [...new Set(items.map((s) => s.segment_name))]
  const barData = years.map((y) => {
    const row: Record<string, number | string> = { year: String(y) }
    for (const seg of byYear[y]) row[seg.segment_name] = seg.revenue || 0
    return row
  })

  const handleCreate = () => {
    if (!formName.trim()) return
    createSeg.mutate({
      bsns_year: formYear, segment_type: segType, segment_name: formName,
      revenue: formRevenue ? parseFloat(formRevenue) : undefined,
      ratio: formRatio ? parseFloat(formRatio) : undefined,
    }, { onSuccess: () => { setFormName(""); setFormRevenue(""); setFormRatio("") } })
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <SegmentTabs tabs={SEG_TABS} value={segType} onChange={setSegType} />
        <Button size="sm" onClick={() => setShowForm(!showForm)}>{showForm ? "취소" : "+ 데이터 추가"}</Button>
      </div>

      {showForm && (
        <Card>
          <CardContent className="pt-5 flex flex-wrap items-end gap-3">
            <Label className="text-xs text-muted-foreground flex-col items-start gap-1">
              연도 <Input type="number" value={formYear} onChange={(e) => setFormYear(parseInt(e.target.value))} className="w-[100px] mt-1" />
            </Label>
            <Label className="text-xs text-muted-foreground flex-col items-start gap-1">
              부문명 <Input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="예: 반도체" className="w-[140px] mt-1" />
            </Label>
            <Label className="text-xs text-muted-foreground flex-col items-start gap-1">
              매출액 (원) <Input type="number" value={formRevenue} onChange={(e) => setFormRevenue(e.target.value)} className="w-[140px] mt-1" />
            </Label>
            <Label className="text-xs text-muted-foreground flex-col items-start gap-1">
              비율 (%) <Input type="number" value={formRatio} onChange={(e) => setFormRatio(e.target.value)} className="w-[80px] mt-1" />
            </Label>
            <Button onClick={handleCreate}>추가</Button>
          </CardContent>
        </Card>
      )}

      {isLoading && <p className="text-muted-foreground">로딩 중...</p>}
      {items.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-center py-10">"데이터 추가" 버튼으로 직접 입력해주세요.</p>
      )}

      {items.length > 0 && (
        <>
          <div className="grid grid-cols-3 gap-5">
            <ChartCard title={`${segType === "division" ? "사업부문별" : "사업지역별"} 매출 비중 (${latestYear})`}>
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={95}
                    label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(1)}%`} labelLine={{ strokeWidth: 1 }}>
                    {pieData.map((_, i) => <Cell key={i} fill={RAW_COLORS[i % RAW_COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v) => formatKrw(Number(v))} />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="매출액 합계 추이" className="col-span-2">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={barData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="year" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatKrw(v)} />
                  <Tooltip formatter={(v) => formatKrw(Number(v))} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {allSegNames.map((name, i) => (
                    <Bar key={name} dataKey={name} stackId="a" fill={RAW_COLORS[i % RAW_COLORS.length]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-center w-[80px]">연도</TableHead>
                <TableHead>부문명</TableHead>
                <TableHead className="text-right">매출액</TableHead>
                <TableHead className="text-right w-[80px]">비율</TableHead>
                <TableHead className="w-[60px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="text-center">{s.bsns_year}</TableCell>
                  <TableCell>{s.segment_name}</TableCell>
                  <TableCell className="text-right">{s.revenue ? formatKrw(s.revenue) : "-"}</TableCell>
                  <TableCell className="text-right">{s.ratio ? `${s.ratio}%` : "-"}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" className="text-destructive text-xs h-6" onClick={() => deleteSeg.mutate(s.id)}>삭제</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
      {/* 다음 질문 — dead-end 제거 (P2-3) */}
      <NextQuestions stockCode={stockCode} context="business" />
    </div>
  )
}
