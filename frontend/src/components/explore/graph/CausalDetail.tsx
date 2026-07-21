import { useState } from "react"
import { ArrowRight, Loader2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { apiQuery, apiComputeQuery, STALE } from "@/api/query"
import { Badge } from "@/components/ui/badge"
import { formatKrw } from "@/utils/format"
import { cn } from "@/lib/utils"
import { NODE_LABEL, type WEdge } from "./types"

/** 세계관 노드 패널·이슈 디테일 공용 — 인과 엣지 행 + 수혜 종목 + 업사이드 모델. */

export function EdgeContextRow({ e, dir }: { e: WEdge; dir: "in" | "out" }) {
  // dir=in: {상대} → 이 노드 (원인) / dir=out: 이 노드 → {상대} (결과)
  const other = dir === "in" ? e.from : e.to
  const otherType = dir === "in" ? e.from_type : e.to_type
  return (
    <li className="rounded-lg border px-2.5 py-1.5 space-y-1">
      <div className="flex items-center gap-1.5 flex-wrap text-sm">
        {dir === "in" && <><span className="font-medium">{other}</span><ArrowRight className="h-3 w-3 text-muted-foreground" /></>}
        <Badge variant="outline" className="text-[9px]">{e.rel === "BENEFITS_FROM" ? "수혜" : "인과"}</Badge>
        {dir === "out" && <><ArrowRight className="h-3 w-3 text-muted-foreground" /><span className="font-medium">{other}</span></>}
        {otherType && <span className="text-[9px] text-muted-foreground">{NODE_LABEL[otherType] ?? otherType}</span>}
        {e.reference_period && <span className="text-[9px] text-muted-foreground">· {e.reference_period}</span>}
        {e.geo_scope && <Badge variant="outline" className="text-[9px]">{e.geo_scope}</Badge>}
        {e.corroborated_by >= 2 && <Badge variant="outline" className="text-[9px] text-primary border-primary/40">{e.corroborated_by}개 확인</Badge>}
        {e.contested && <Badge variant="destructive" className="text-[9px]">상충</Badge>}
      </div>
      {e.mechanism && <p className="text-xs text-muted-foreground leading-snug">{e.mechanism}</p>}
    </li>
  )
}

export interface BeneficiaryCandidate {
  stock_code: string; entity_id: number; name: string
  rs_short: number | null; rs_prev: number | null
  per: number | null; pbr: number | null; market_cap: number | null; pos_52w: number | null
  co_mentions: number; relevance: number | null
}

interface UpsideScenario {
  name: string; prob: number | null; assumptions: string[]
  revenue_delta_pct: number | null; margin: number | null; eps_new: number | null
  multiple: number | null; fair_price: number | null; upside_pct: number | null
}
interface UpsideModel {
  status: string; method?: string
  scenarios?: UpsideScenario[]
  downside?: { floor_price: number | null; downside_pct: number | null; basis: string } | null
  invalidation?: string[]; summary?: string
  cached?: boolean; updated_at?: string | null
}

// 업사이드 모델 (Phase 2, D-035) — 저장분 캐시 반환(즉시), '다시 계산' 시에만 opus 재생성.
function UpsideResult({ stock, event }: { stock: string; event: string }) {
  const [nonce, setNonce] = useState(0)   // 증가 시 refresh=1로 재생성
  const { data, isFetching, isError } = useQuery(
    apiComputeQuery<UpsideModel>({
      key: ["spine", "beneficiary", "upside", stock, event, nonce],
      url: `/api/spine/beneficiary/upside?stock=${stock}&event=${encodeURIComponent(event)}${nonce > 0 ? "&refresh=1" : ""}`,
      enabled: true,
    }),
  )
  if (isFetching && !data) {
    return <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <Loader2 className="h-3 w-3 animate-spin" /> 업사이드 모델 생성 중… (opus, 수십 초)</div>
  }
  if (isError || !data || data.status !== "ok" || !data.scenarios?.length) {
    return <div className="mt-1.5 text-[11px] text-muted-foreground">업사이드 모델 생성 실패 — 재시도.</div>
  }
  return (
    <div className="mt-1.5 space-y-1.5 border-t pt-1.5 text-[11px]">
      <div className="flex items-center gap-1.5">
        {data.method && <Badge variant="secondary" className="text-[9px]">{data.method}</Badge>}
        {data.summary && <span className="text-muted-foreground">{data.summary}</span>}
      </div>
      {data.scenarios.map((s) => (
        <div key={s.name}>
          <div className="flex items-center gap-1.5">
            <span className="font-medium">{s.name}{s.prob != null ? ` (${Math.round(s.prob * 100)}%)` : ""}</span>
            {s.upside_pct != null && (
              <span className={cn("tabular-nums font-medium", s.upside_pct >= 0 ? "text-up" : "text-down")}>
                {s.upside_pct >= 0 ? "+" : ""}{Math.round(s.upside_pct)}%
              </span>
            )}
            {s.fair_price != null && <span className="text-muted-foreground tabular-nums">적정 {formatKrw(s.fair_price)}</span>}
          </div>
          {s.assumptions?.length > 0 && (
            <div className="text-muted-foreground pl-1">↳ {s.assumptions.join(" · ")}</div>
          )}
        </div>
      ))}
      {data.downside && (data.downside.downside_pct != null || data.downside.basis) && (
        <div className="text-muted-foreground">
          하방 {data.downside.downside_pct != null ? `${Math.round(data.downside.downside_pct)}%` : ""}
          {data.downside.basis ? ` — ${data.downside.basis}` : ""}
        </div>
      )}
      {data.invalidation?.length ? (
        <div className="text-muted-foreground">무효화: {data.invalidation.join(" · ")}</div>
      ) : null}
      <div className="flex items-center gap-2 text-[9px] text-muted-foreground/70">
        <span>가정 기반 추정 · 범위+조건부 · 검증 필요</span>
        {data.cached && data.updated_at && <span>· 저장분 {data.updated_at.slice(0, 10)}</span>}
        <button onClick={() => setNonce((n) => n + 1)} className="ml-auto text-primary hover:underline">다시 계산</button>
      </div>
    </div>
  )
}

function BeneficiaryRow({ c, event }: { c: BeneficiaryCandidate; event: string }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="rounded-lg border px-2.5 py-1.5">
      <div className="flex items-center gap-1.5 flex-wrap">
        <a href={`/analyze/${c.stock_code}/summary`} className="font-medium text-sm hover:underline">{c.name}</a>
        {c.rs_short != null && (
          <Badge variant="outline" className="text-[9px] text-primary border-primary/40">RS {c.rs_short}</Badge>
        )}
        {c.relevance != null && <span className="text-[9px] text-muted-foreground">관련도 {Math.round(c.relevance * 100)}%</span>}
        {c.pos_52w != null && <span className="text-[9px] text-muted-foreground">52주 {c.pos_52w}%</span>}
        <button onClick={() => setOpen((o) => !o)}
          className="ml-auto text-[10px] text-primary hover:underline">{open ? "접기" : "업사이드"}</button>
      </div>
      <div className="flex gap-2 text-[10px] text-muted-foreground mt-0.5 tabular-nums">
        {c.market_cap != null && <span>{formatKrw(c.market_cap)}</span>}
        {c.per != null && <span>PER {c.per.toFixed(1)}배</span>}
        {c.pbr != null && <span>PBR {c.pbr.toFixed(2)}배</span>}
      </div>
      {open && <UpsideResult stock={c.stock_code} event={event} />}
    </li>
  )
}

// ── 통합 체인: scenario 파급 논리로 지목된 수혜/피해 종목 (D-035, 공동언급 아님) ──
export interface ScenarioBeneficiary {
  name: string; rel: string | null; reason: string | null
  stock_code: string | null; entity_id: number | null
  rs_short: number | null; per: number | null; pbr: number | null
  market_cap: number | null; pos_52w: number | null
}

function ScenarioBeneficiaryRow({ b, event }: { b: ScenarioBeneficiary; event: string }) {
  const [open, setOpen] = useState(false)
  const harm = b.rel === "피해"
  return (
    <li className="rounded-lg border px-2.5 py-1.5">
      <div className="flex items-center gap-1.5 flex-wrap">
        <Badge variant="outline" className={cn("text-[9px]", harm ? "text-down border-down/40" : "text-up border-up/40")}>
          {b.rel ?? "수혜"}
        </Badge>
        {b.stock_code
          ? <a href={`/analyze/${b.stock_code}/summary`} className="font-medium text-sm hover:underline">{b.name}</a>
          : <span className="font-medium text-sm">{b.name}</span>}
        {b.rs_short != null && <Badge variant="outline" className="text-[9px] text-primary border-primary/40">RS {b.rs_short}</Badge>}
        {b.pos_52w != null && <span className="text-[9px] text-muted-foreground">52주 {b.pos_52w}%</span>}
        {!b.stock_code && <span className="text-[9px] text-muted-foreground">미상장·미보유</span>}
        {b.stock_code && !harm && (
          <button onClick={() => setOpen((o) => !o)}
            className="ml-auto text-[10px] text-primary hover:underline">{open ? "접기" : "업사이드"}</button>
        )}
      </div>
      {b.reason && <p className="text-xs text-muted-foreground leading-snug mt-0.5">{b.reason}</p>}
      {(b.market_cap != null || b.per != null) && (
        <div className="flex gap-2 text-[10px] text-muted-foreground mt-0.5 tabular-nums">
          {b.market_cap != null && <span>{formatKrw(b.market_cap)}</span>}
          {b.per != null && <span>PER {b.per.toFixed(1)}배</span>}
          {b.pbr != null && <span>PBR {b.pbr.toFixed(2)}배</span>}
        </div>
      )}
      {open && b.stock_code && <UpsideResult stock={b.stock_code} event={event} />}
    </li>
  )
}

/** scenario 파급 체인의 논리 기반 수혜/피해 종목 (통합 체인 — 이슈→파급 논리→종목→업사이드). */
export function ScenarioBeneficiaries({ items, event }: { items: ScenarioBeneficiary[]; event: string }) {
  if (!items?.length) return null
  return (
    <div>
      <div className="text-xs font-medium mb-1.5 text-muted-foreground">
        수혜·피해 종목 ({items.length}) <span className="font-normal">· 파급 논리로 지목 (공동언급 아님)</span>
      </div>
      <ul className="space-y-1.5">
        {items.map((b, i) => <ScenarioBeneficiaryRow key={`${b.name}-${i}`} b={b} event={event} />)}
      </ul>
    </div>
  )
}

/** 수혜 섹터/테마 → 종목 후보 목록 (공동언급+RS·밸류·관련도, 각 행에 업사이드 버튼). */
export function BeneficiaryList({ sector }: { sector: string }) {
  const { data, isLoading } = useQuery(
    apiQuery<BeneficiaryCandidate[]>({
      key: ["spine", "beneficiary", sector],
      url: `/api/spine/beneficiary/screen?sector=${encodeURIComponent(sector)}&limit=10`,
      staleTime: STALE.medium,
    }),
  )
  if (isLoading) return <div className="text-xs text-muted-foreground">수혜 후보 탐색 중…</div>
  const items = data ?? []
  if (items.length === 0) return null
  return (
    <div>
      <div className="text-xs font-medium mb-1.5 text-muted-foreground">
        수혜 후보 종목 ({items.length}) <span className="font-normal">· 문서 공동언급 + RS·밸류</span>
      </div>
      <ul className="space-y-1.5">
        {items.map((c) => <BeneficiaryRow key={c.stock_code} c={c} event={sector} />)}
      </ul>
    </div>
  )
}
