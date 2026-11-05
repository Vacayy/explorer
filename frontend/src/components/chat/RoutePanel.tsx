import { Badge } from "@/components/ui/badge"
import type { ChatRoute } from "@/types"
import { formatNumber } from "@/utils/format"

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

/** 도구 → 근거 묶음 이름 (답변 머리 '근거 수집 · 시세 1건 · 최근 공시 5건 …', 시안 Chat) */
const TOOL_LABEL: Record<string, string> = {
  get_quote: "시세", get_price_history: "시세 추이", search_docs: "문서 검색", open_doc: "문서 원문", get_transcripts: "컨콜",
  get_trade: "수출입", get_saved: "저장 자료", get_study: "스터디", get_proxies: "지표", get_narrative: "내러티브",
  get_worldmodel: "월드모델", get_knowledge: "지식", get_questions: "질문", get_lens: "투자 렌즈", get_regime: "국면",
  get_us_briefing: "미국장 브리핑", get_pricing_ledger: "시장 프라이싱", get_portfolio: "포트폴리오",
}
const RECENT_LABEL: Record<string, string> = {
  docs: "최근 문서", scrap: "최근 스크랩", disclosures: "최근 공시", narratives: "최근 서사", digests: "최근 다이제스트",
  youtube: "최근 유튜브", signals: "최근 신호", actions: "최근 기업활동",
}

/** 도구 호출을 근거 묶음별 건수로 모은다 — 같은 도구를 여러 번 불렀으면 한 줄로 합친다. 오류 난 호출은 건수 0으로 센다 */
export function evidenceSummary(route: ChatRoute): string[] {
  const by = new Map<string, number>()
  for (const t of route.tools ?? []) {
    const kind = typeof t.args?.kind === "string" ? t.args.kind : ""
    const label = t.name === "list_recent" ? RECENT_LABEL[kind] ?? "최근 목록" : TOOL_LABEL[t.name] ?? t.name
    by.set(label, (by.get(label) ?? 0) + (t.error ? 0 : t.n ?? 0))
  }
  return [...by].map(([label, n]) => `${label} ${formatNumber(n)}건`)
}

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
