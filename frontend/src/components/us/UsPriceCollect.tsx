import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DownloadCloud, LoaderCircle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/api/client'
import { Button } from '@/components/ui/button'
import { formatNumber, formatRelativeTime } from '@/utils/format'

/** 미국 시세 보유 현황 + 버튼 주도 수집(D-100). 시세는 렌즈를 열 때만 채워져 비거나 묵기 쉬웠다(docs/specs/us-dossier.md). */
export interface UsPriceStatus { ticker: string; rows: number; first_date: string | null; last_date: string | null; fetched_at: string | null; latest_available: string | null; stale_days: number | null; state: 'missing' | 'stale' | 'fresh' }

export function useUsPriceStatus(ticker: string) {
  return useQuery({ queryKey: ['spine', 'us-price-status', ticker], queryFn: async () => (await api.get<UsPriceStatus>(`/api/spine/us/${ticker}/prices/status`)).data, staleTime: 60_000 })
}

export function UsPriceCollect({ ticker }: { ticker: string }) {
  const client = useQueryClient()
  const status = useUsPriceStatus(ticker)
  const collect = useMutation({
    mutationFn: async () => (await api.post<UsPriceStatus & { collected_rows: number }>(`/api/spine/us/${ticker}/prices/collect`, null, { params: { period: '2y' } })).data,
    onSuccess: data => {
      client.setQueryData(['spine', 'us-price-status', ticker], data)
      client.invalidateQueries({ queryKey: ['company-prices', ticker, 'us'] })
      client.invalidateQueries({ queryKey: ['spine', 'technical-scan', 'us', ticker] })
      client.invalidateQueries({ queryKey: ['spine', 'chart-structure'] })
      toast.success(`${ticker} 시세 ${formatNumber(data.collected_rows)}행을 받았습니다.`, { description: `최신 거래일 ${data.last_date ?? '-'} · yfinance 2년 일봉` })
    },
    onError: error => toast.error('시세를 받지 못했습니다.', { description: (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? (error as Error).message }),
  })
  const s = status.data
  const label = !s ? '시세 확인 중…' : s.state === 'missing' ? '저장된 시세가 없습니다' : `시세 ${formatNumber(s.rows)}일 · 최신 ${s.last_date}${s.state === 'stale' ? ` (다른 종목 최신일보다 ${formatNumber(s.stale_days ?? 0)}일 뒤)` : ''}${s.fetched_at ? ` · ${formatRelativeTime(s.fetched_at)} 수집` : ''}`
  return <div className="mt-2 flex flex-wrap items-center gap-2 text-caption text-muted-foreground" aria-label="미국 시세 수집">
    <span className={s?.state === 'missing' ? 'text-hypothesis' : undefined}>{label}</span>
    <Button size="sm" variant={s?.state === 'fresh' ? 'ghost' : 'outline'} className="h-7 px-2.5 text-caption" disabled={collect.isPending || status.isPending} onClick={() => collect.mutate()} aria-label="시세 수집">
      {collect.isPending ? <LoaderCircle className="size-3.5 animate-spin" /> : <DownloadCloud className="size-3.5" />}{collect.isPending ? '받는 중…' : s?.state === 'missing' ? '시세 수집' : '시세 갱신'}
    </Button>
    {s?.state !== 'fresh' && s && <span>차트·기술적 분석·구조 그리기는 저장된 시세로 계산합니다.</span>}
  </div>
}
