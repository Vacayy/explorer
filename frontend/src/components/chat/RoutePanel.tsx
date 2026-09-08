import { Badge } from "@/components/ui/badge"
import type { ChatRoute } from "@/types"

const INTENT_LABEL: Record<string, string> = {
  lookup: "조회", event: "사건 설명", synthesis: "종합 분석", person: "인물", followup: "후속질문",
  refuse: "거부(예측·판단 요구)", scenario: "파급 시나리오",
}
const LENS_LABEL: Record<string, string> = { pattern: "패턴(종목)", industry: "산업", worldview: "세계관" }

export const fmtSec = (ms?: number) => (ms == null ? "-" : `${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 1)}초`)
const fmtArgs = (args?: Record<string, unknown>) =>
  Object.entries(args ?? {})
    .filter(([, v]) => v != null && v !== "" && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : String(v)}`)
    .join(", ")

/** 총 소요 — 라우팅+점검+종합 */
export function routeTotalMs(route: ChatRoute): number | undefined {
  const t = route.timings_ms ?? {}
  const parts = [t.route, t.review, t.synth].filter((x): x is number => x != null)
  return parts.length ? parts.reduce((a, b) => a + b, 0) : undefined
}

/** 답변 경로 — 어떤 의도로 읽고, 어떤 도구를 어떤 인자로 불러 근거 몇 건을 모아 답했는지 (route_json, D-131·D-134) */
export function RoutePanel({ route }: { route: ChatRoute }) {
  const tools = route.tools ?? []
  const steps = route.steps ?? []
  const process = route.process ?? []
  return (
    <div className="rounded-xl border bg-muted/30 px-4 py-3 text-xs space-y-3">
      {/* 과정 서술 — 코드가 로그를 문장으로 푼 것(steps) + 종합 모델의 판단 메모(process). D-134 */}
      {steps.length > 0 && (
        <ol className="list-decimal pl-4 space-y-1 leading-relaxed">
          {steps.map((st, i) => <li key={i}>{st}</li>)}
        </ol>
      )}
      {process.length > 0 && (
        <div className="rounded-lg bg-[color-mix(in_srgb,var(--hypothesis)_8%,var(--card))] px-3 py-2">
          <p className="text-muted-foreground mb-1">모델의 판단 메모</p>
          <ul className="list-disc pl-4 space-y-1 leading-relaxed">
            {process.map((x, i) => <li key={i}>{x}</li>)}
          </ul>
        </div>
      )}
      <div className="border-t pt-2.5 space-y-2">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
          <span>의도 <span className="text-foreground">{INTENT_LABEL[route.intent ?? ""] ?? route.intent ?? "-"}</span></span>
          {route.lens && <span>렌즈 <span className="text-foreground">{LENS_LABEL[route.lens] ?? route.lens}</span></span>}
          <span>근거 <span className="text-foreground tabular-nums">{route.evidence_n}건</span></span>
          <span>
            라우팅 <span className="tabular-nums">{fmtSec(route.timings_ms?.route)}</span>
            {route.timings_ms?.review != null && <> · 점검 <span className="tabular-nums">{fmtSec(route.timings_ms.review)}</span></>}
            {" "}· 종합 <span className="tabular-nums">{fmtSec(route.timings_ms?.synth)}</span>
          </span>
          {route.model && <span>{route.model}</span>}
        </div>
        {route.standalone_question && (
          <p><span className="text-muted-foreground">독립형 질문</span> {route.standalone_question}</p>
        )}
        {route.entities && route.entities.length > 0 && (
          <div className="flex flex-wrap gap-1 items-center">
            <span className="text-muted-foreground">엔티티</span>
            {route.entities.map((e, i) => (
              <Badge key={i} variant="outline" className="text-[10px] font-normal">{e.name}{e.kind ? ` · ${e.kind}` : ""}</Badge>
            ))}
          </div>
        )}
        {tools.length > 0 ? (
          <ol className="space-y-1">
            {tools.map((t, i) => (
              <li key={i} className="flex flex-wrap gap-x-2 items-baseline">
                <span className="tabular-nums text-muted-foreground">{i + 1}.</span>
                {(t as { round?: number }).round === 2 && <Badge variant="outline" className="text-[9px] font-normal px-1 py-0">추가</Badge>}
                <code className="text-[11px]">{t.name}({fmtArgs(t.args)})</code>
                {t.error ? (
                  <span className="text-destructive">{t.error}</span>
                ) : (
                  <span className="text-muted-foreground tabular-nums">→ {t.n ?? 0}건 · {fmtSec(t.ms)}</span>
                )}
                {t.note && <span className="text-muted-foreground">— {t.note}</span>}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground">도구 호출 없음</p>
        )}
      </div>
    </div>
  )
}
