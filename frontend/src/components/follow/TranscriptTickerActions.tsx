// 종목 단위 컨콜 버튼 — ① 가장 최근 실적 발표 조사(SEC 8-K·yfinance, AV 한도 무관) ② 이 종목만 수집.
// 수집은 전체 수집과 같은 사슬(POST /collect?tickers=)이라 진행 상태는 위 '컨콜 수집' 카드가 보여 준다.
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Download, Search } from "lucide-react"
import { toast } from "sonner"
import { postJson } from "@/api/query"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { useCheckLatestCall } from "@/hooks/useTranscripts"
import type { TranscriptCheck } from "@/types"

const AV_BUDGET = 3   // 한 종목이면 최근 분기 몇 개면 충분 — 하루 한도(25)를 전체 수집 몫으로 남긴다

export function TranscriptTickerActions({ ticker, currentId, onSelect }: { ticker: string; currentId: number; onSelect: (id: number) => void }) {
  const qc = useQueryClient()
  const check = useCheckLatestCall()
  const collect = useMutation({
    mutationFn: () => postJson(`/api/spine/transcript/collect`, null, { params: { tickers: ticker, budget: AV_BUDGET } }),
    onSuccess: () => {
      toast.success(`${ticker} 수집을 시작했습니다 — 진행은 위 '컨콜 수집' 카드에서`)
      qc.invalidateQueries({ queryKey: ["spine", "transcript", "collect", "status"] })
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <Button variant="outline" size="xs" onClick={() => check.mutate(ticker, { onError: (e) => toast.error(e.message) })} disabled={check.isPending}
          title="SEC 실적 발표·yfinance 발표일을 지금 다시 읽습니다 (Alpha Vantage 한도 안 씀)">
          {check.isPending ? <Spinner className="h-3 w-3" /> : <Search className="h-3 w-3" />} 최근 발표 조사
        </Button>
        <Button variant="outline" size="xs" onClick={() => collect.mutate()} disabled={collect.isPending}
          title={`이 종목만 수집 — Motley Fool 먼저, 없으면 Alpha Vantage ${AV_BUDGET}건까지`}>
          <Download className="h-3 w-3" /> 이 종목 수집
        </Button>
      </div>
      {check.data && <CheckResult r={check.data} currentId={currentId} onSelect={onSelect} />}
    </div>
  )
}

function CheckResult({ r, currentId, onSelect }: { r: TranscriptCheck; currentId: number; onSelect: (id: number) => void }) {
  const rel = r.latest_release
  const cal = r.calendar
  return (
    <p className="text-[11px] text-muted-foreground">
      {rel ? <>최근 실적 발표 <b className="text-foreground">{rel.date}</b> ({rel.cy ?? `FY${rel.fiscal_year} ${rel.fiscal_period}`}, SEC 8-K)</> : "SEC 실적 발표 기록 없음"}
      {cal?.next_report_date && ` · 다음 ${cal.next_report_date}`}
      {cal?.last_report_date && rel && cal.last_report_date !== rel.date && ` · yfinance는 ${cal.last_report_date}`}
      {rel && (r.transcript_id ? (
        r.transcript_id === currentId ? " · 녹취록 저장됨(지금 보는 분기)" : (
          <> · 녹취록 저장됨 <Button variant="link" size="xs" className="h-auto p-0 text-[11px]" onClick={() => onSelect(r.transcript_id!)}>그 분기 보기</Button></>
        )
      ) : r.fool?.available ? " · 녹취록 미수집 — Motley Fool에 올라옴, '이 종목 수집'으로 받으세요"
        : r.fool?.available === false ? " · 녹취록 미수집 — Motley Fool에 아직 없음(Alpha Vantage로 시도 가능)"
        : r.fool?.error ? ` · Fool 확인 실패: ${r.fool.error}` : "")}
      {r.sec_error && <span className="text-hypothesis"> · SEC 조회 실패: {r.sec_error}</span>}
    </p>
  )
}
