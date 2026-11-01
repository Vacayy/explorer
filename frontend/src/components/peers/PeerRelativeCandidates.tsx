import { selectPeerPreset } from '@/lib/peerPresets'
import { Link, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import PeriodToggle from '@/components/shared/PeriodToggle'
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatPercent, formatPp } from '@/utils/format'
import type { PeerGroupPerformance } from '@/types/peer'

/** Cross-sectional screen, not a newly occurring event or an alert. */
export function PeerRelativeCandidates({ groups }: { groups: PeerGroupPerformance[] }) {
  const [params, setParams] = useSearchParams()
  const direction = params.get('relative') === 'under' ? 'under' : 'over'
  const rows = groups.filter(group => group.scope === 'product' && group.memberCount >= 3 && group.returnPct !== null)
    .flatMap(group => group.members.map(member => ({ ...member, groupId: group.id, groupName: group.name, count: group.memberCount })))
    .filter(row => row.excessPp !== null && (direction === 'over' ? row.excessPp > 0 : row.excessPp < 0))
    .sort((a, b) => (direction === 'over' ? -1 : 1) * (a.excessPp! - b.excessPp!) || a.code.localeCompare(b.code))
  const open = (group: string, code: string) => setParams(previous => {
    const next = selectPeerPreset(previous, group); next.set('stock', code); return next
  })
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="font-medium">Peer 대비 강약 종목 찾기</h3>
      <PeriodToggle value={direction} onChange={value => setParams(previous => { const next = new URLSearchParams(previous); next.set('relative', value); return next })} options={[{ value: 'over', label: '상대 강세' }, { value: 'under', label: '상대 약세' }]} />
    </div>
    <p className="text-caption text-muted-foreground">가격이 완전한 3개 이상 기업의 제품·공정 그룹에서 조회합니다. 양수는 상대 강세, 음수는 상대 약세이며 절대 상승·하락과 다릅니다. 새로 발생한 신호나 알림은 아닙니다.</p>
    <p role="status" className="text-caption text-muted-foreground">{new Set(rows.map(row => row.code)).size}개 고유 기업 · {rows.length}개 종목–그룹 관계. 한 기업이 여러 그룹에 나타날 수 있습니다.</p>
    {rows.length === 0 ? <p role="status" className="border border-border p-4 text-sm">선택한 분류에서 비교 조건을 충족한 종목이 없습니다. 제품·공정 또는 전체 범위를 선택해 주세요.</p> : <Table>
      <TableCaption>초과수익률 크기순. 그룹별 위험·사업구성이 달라 숫자를 위험 조정 알파로 해석하지 않습니다.</TableCaption>
      <TableHeader><TableRow><TableHead>종목</TableHead><TableHead>비교 그룹</TableHead><TableHead className="text-right">가격변동률</TableHead><TableHead className="text-right">Peer 평균</TableHead><TableHead className="text-right">Peer 대비</TableHead><TableHead className="text-right">순위</TableHead></TableRow></TableHeader>
      <TableBody>{rows.map(row => <TableRow key={`${row.groupId}-${row.code}`}>
        <TableCell><Link className="font-medium hover:underline" to={`/analyze/${row.code}/summary`}>{row.name}</Link></TableCell>
        <TableCell><Button variant="link" className="h-auto whitespace-normal p-0 text-left" onClick={() => open(row.groupId, row.code)}>{row.groupName}</Button></TableCell>
        <TableCell className={`text-right tabular-nums ${row.returnPct !== null && row.returnPct > 0 ? 'text-up' : 'text-down'}`}>{formatPercent(row.returnPct)}</TableCell>
        <TableCell className="text-right tabular-nums">{formatPercent(row.peerReturnPct)}</TableCell>
        <TableCell className={`text-right tabular-nums ${direction === 'over' ? 'text-up' : 'text-down'}`}>{formatPp(row.excessPp, 1)}</TableCell>
        <TableCell className="text-right tabular-nums">{row.rank} / {row.count}</TableCell>
      </TableRow>)}</TableBody>
    </Table>}
  </div>
}
