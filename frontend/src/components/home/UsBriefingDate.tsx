import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useUsBriefingDates } from '@/hooks/useUsBriefing'
import { useUrlParam } from '@/hooks/useUrlParam'

/** Stored session selection shared by the original dashboard and US card. */
export function UsBriefingDate() {
  const { data: dates = [] } = useUsBriefingDates()
  const [day, setDay] = useUrlParam('usdate', 'latest')
  if (dates.length < 2) return null
  return <Select value={day} onValueChange={setDay}>
    <SelectTrigger className="h-7 w-32 text-caption" aria-label="브리핑 날짜"><SelectValue placeholder="날짜" /></SelectTrigger>
    <SelectContent>
      <SelectItem value="latest">최신</SelectItem>
      {dates.map(d => <SelectItem key={d.trade_date} value={d.trade_date}>{d.trade_date}</SelectItem>)}
    </SelectContent>
  </Select>
}
