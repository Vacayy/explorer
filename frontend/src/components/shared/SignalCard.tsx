import { useState } from "react"
import { Link } from "react-router-dom"
import { ChevronDown, ChevronUp } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { SpineSignal } from "@/types"

const SIGNAL_LABEL: Record<string, string> = {
  mention_surge: "언급 급증",
  neglect: "소외",
  export_change: "수출 변화",
  high_52w: "52주 신고가",
  consensus_extreme: "컨센서스 극단",
}

/**
 * 신호 카드 (확장형 카드 시스템 — product-v2.md)
 * signal_type별 본문이 같은 프레임을 공유한다. 새 신호 타입 = 본문 렌더러만 추가.
 * 규율: 근거 문서는 항상 접근 가능해야 한다 ("왜 이 신호?"가 1클릭).
 */
export function SignalCard({ signal: s, onKeywordClick }: {
  signal: SpineSignal
  onKeywordClick?: (keyword: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const p = s.payload
  const docs = p.docs ?? []
  const visibleDocs = expanded ? docs : docs.slice(0, 2)

  return (
    <Card>
      <CardContent className="py-3.5 space-y-2.5">
        {/* 헤더 */}
        <div className="flex items-center gap-2">
          {s.stock_code ? (
            <Link to={`/analyze/${s.stock_code}/summary`} className="font-semibold text-primary hover:underline">
              {s.entity_name}
            </Link>
          ) : (
            <span className="font-semibold">{s.entity_name}</span>
          )}
          {s.stock_code && <span className="text-xs text-muted-foreground tabular-nums">{s.stock_code}</span>}
          <Badge variant="secondary" className="text-[10px]">{SIGNAL_LABEL[s.signal_type] ?? s.signal_type}</Badge>
          <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{s.date}</span>
        </div>

        {/* 본문 — signal_type별 렌더러 */}
        {s.signal_type === "mention_surge" && (
          <div className="text-sm">
            최근 7일 <span className="font-bold text-up text-base">{p.count_7d ?? "-"}회</span> 언급
            <span className="text-muted-foreground text-xs"> · 직전 7일 {p.baseline_7d ?? 0}회</span>
          </div>
        )}
        {s.signal_type === "neglect" && (
          <p className="text-xs text-muted-foreground">
            PER <span className="font-semibold text-foreground">{p.per}배</span> · ROE{" "}
            <span className="font-semibold text-foreground">{p.roe}%</span> · 시총{" "}
            {p.market_cap != null ? `${(p.market_cap / 1e12).toFixed(2)}조` : "-"} [{p.market}]
            <br />저평가·흑자인데 최근 {p.window_days ?? 30}일 언급 0 — 주목의 부재가 신호
          </p>
        )}
        {s.signal_type === "consensus_extreme" && (
          <p className="text-xs text-muted-foreground">
            최근 {p.window_days ?? 14}일 감성{" "}
            <span className={`font-semibold ${p.direction === "optimism" ? "text-up" : "text-down"}`}>
              {p.direction === "optimism" ? "낙관" : "비관"} {p.ratio != null ? `${Math.round(p.ratio * 100)}%` : "-"}
            </span>
            <span className="tabular-nums"> (긍정 {p.pos} / 부정 {p.neg})</span>
            <br />만장일치에 가까운 컨센서스 — 진자가 극단에 있다는 관찰
          </p>
        )}
        {s.signal_type === "high_52w" && (
          <div className="text-sm space-x-2">
            <span>고가 <span className="font-bold text-up text-base tabular-nums">{p.high?.toLocaleString()}</span></span>
            <span className="text-muted-foreground text-xs tabular-nums">
              전고점 {p.prior_high_52w?.toLocaleString()} 경신 (+{p.breakout_pct}%) · 종가 {p.close?.toLocaleString()}
            </span>
          </div>
        )}

        {/* 키워드 칩 → 피드 필터로 */}
        {p.keywords && p.keywords.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {p.keywords.map((k) => (
              <Badge
                key={k}
                variant="outline"
                className="text-[10px] font-normal cursor-pointer hover:bg-muted"
                onClick={() => onKeywordClick?.(k)}
              >
                {k}
              </Badge>
            ))}
          </div>
        )}

        {/* LLM 해석 — 가설 스타일 (epistemic 규율) */}
        {s.interpretation && (
          <p className="text-xs border-l-2 border-hypothesis pl-2 text-muted-foreground">
            <span className="text-hypothesis font-medium">해석</span> {s.interpretation}
            {s.interpretation_model && (
              <span className="ml-1 opacity-70">({s.interpretation_model})</span>
            )}
          </p>
        )}

        {/* 근거 문서 */}
        {docs.length > 0 && (
          <div className="border-t pt-2 space-y-1">
            <div className="text-[11px] text-muted-foreground">근거 문서 {docs.length}건</div>
            <ul className="space-y-0.5">
              {visibleDocs.map((d, i) => (
                <li key={i} className="truncate">
                  {d.id ? (
                    <Link to={`/doc/${d.id}`} className="text-xs hover:underline text-foreground/80">
                      · {d.title}
                    </Link>
                  ) : (
                    <a href={d.url} target="_blank" rel="noreferrer"
                       className="text-xs hover:underline text-foreground/80">
                      · {d.title}
                    </a>
                  )}
                </li>
              ))}
            </ul>
            {docs.length > 2 && (
              <Button variant="ghost" size="xs" onClick={() => setExpanded(!expanded)}>
                {expanded ? <><ChevronUp className="h-3 w-3" /> 접기</> : <><ChevronDown className="h-3 w-3" /> {docs.length - 2}건 더보기</>}
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
