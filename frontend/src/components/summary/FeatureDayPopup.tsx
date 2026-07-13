import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Loader2, X } from "lucide-react"
import { explainFeatureDay, type DayExplain, type FeatureDay } from "@/hooks/useFeatureDays"
import { cn } from "@/lib/utils"

/**
 * 특징일 원인 팝업 — 차트 마커 클릭 시. 게으른 조사(haiku 1콜, 이후 캐시).
 * 하이닉스·삼성전자만 실제 LLM 조사 (테스트 범위), 그 외 종목은 마커만 표시.
 */
export function FeatureDayPopup({ stockCode, day, meta, onClose }: {
  stockCode: string
  day: string
  meta?: FeatureDay
  onClose: () => void
}) {
  const [state, setState] = useState<DayExplain | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    setLoading(true)
    explainFeatureDay(stockCode, day)
      .then((r) => { if (alive) setState(r) })
      .catch(() => { if (alive) setState({ note: null, status: "failed", docs: [] }) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [stockCode, day])

  const up = meta?.direction === "up"
  return (
    <div className="mt-2 rounded-lg border bg-card px-4 py-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold tabular-nums">{day}</span>
        {meta && (
          <span className={cn("text-sm font-bold tabular-nums", up ? "text-up" : "text-down")}>
            {meta.ret_pct >= 0 ? "+" : ""}{meta.ret_pct}%
          </span>
        )}
        {meta?.volume_ratio && meta.volume_ratio >= 2 && (
          <span className="text-[11px] text-muted-foreground">거래량 {meta.volume_ratio}배</span>
        )}
        <button onClick={onClose} className="ml-auto text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 그날 무슨 일이 있었는지 조사 중… (수십 초)
        </div>
      ) : state?.status === "no_docs" ? (
        <p className="text-xs text-muted-foreground">이 날짜 전후의 수집 문서가 없어 원인을 조사할 수 없습니다.</p>
      ) : state?.status === "unavailable" ? (
        <p className="text-xs text-muted-foreground">LLM 엔진이 연결되면 조사됩니다.</p>
      ) : state?.note ? (
        <>
          <p className="text-sm leading-relaxed">{state.note}</p>
          {state.docs.length > 0 && (
            <div className="border-t pt-1.5">
              <span className="text-[10px] text-muted-foreground">근거 문서 {state.docs.length}건</span>
              <ul className="mt-0.5 space-y-0.5">
                {state.docs.slice(0, 5).map((d) => (
                  <li key={d.id}>
                    <Link to={`/doc/${d.id}`} className="text-xs text-foreground/80 hover:underline">· {d.title}</Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <span className="block text-[10px] text-muted-foreground">AI 조사 · 수집 문서 근거 — 검증 필요</span>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">조사에 실패했습니다. 다시 클릭하면 재시도됩니다.</p>
      )}
    </div>
  )
}
