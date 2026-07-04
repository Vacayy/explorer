import type { FinancialResponse, KeyMetric } from "@/types"

/** Safely get a key metric value as number */
export function metricValue(metric: KeyMetric | undefined, idx: number): number | null {
  if (!metric) return null
  const v = metric.values[idx]
  if (!v || v === "None") return null
  const n = parseFloat(v)
  return isNaN(n) ? null : n
}

/** Convert raw won to 억 */
export function toEok(v: number | null): number | null {
  return v !== null ? Math.round(v / 1e8) : null
}

/** Build chart data from key_metrics — 3 bars + OPM line */
export function buildRevenueOpChart(data: FinancialResponse) {
  const km = data.key_metrics
  if (!km) return []

  return data.periods.map((p, i) => {
    const rev = toEok(metricValue(km["매출액"], i))
    const op = toEok(metricValue(km["영업이익"], i))
    const net = toEok(metricValue(km["당기순이익"], i))
    const margin = rev && op ? Math.round((op / rev) * 1000) / 10 : null
    return { period: p, 매출액: rev, 영업이익: op, 당기순이익: net, "OPM(%)": margin }
  })
}

export function buildMarginChart(data: FinancialResponse) {
  const km = data.key_metrics
  if (!km) return []

  return data.periods.map((p, i) => {
    const rev = metricValue(km["매출액"], i)
    const gross = metricValue(km["매출총이익"], i)
    const op = metricValue(km["영업이익"], i)
    const net = metricValue(km["당기순이익"], i)
    return {
      period: p,
      매출총이익률: rev && gross ? Math.round((gross / rev) * 1000) / 10 : null,
      영업이익률: rev && op ? Math.round((op / rev) * 1000) / 10 : null,
      순이익률: rev && net ? Math.round((net / rev) * 1000) / 10 : null,
    }
  })
}

export function buildGrowthChart(data: FinancialResponse) {
  const km = data.key_metrics
  if (!km) return []

  return data.periods.map((p, i) => ({
    period: p,
    매출액성장률: km["매출액"]?.yoy[i] ?? null,
    영업이익성장률: km["영업이익"]?.yoy[i] ?? null,
    순이익성장률: km["당기순이익"]?.yoy[i] ?? null,
  }))
}

export function buildRevenueNetChart(data: FinancialResponse) {
  const km = data.key_metrics
  if (!km) return []

  return data.periods.map((p, i) => {
    const rev = toEok(metricValue(km["매출액"], i))
    const net = toEok(metricValue(km["당기순이익"], i))
    const margin = rev && net ? Math.round((net / rev) * 1000) / 10 : null
    return { period: p, 매출액: rev, 당기순이익: net, "순이익률(%)": margin }
  })
}

export function buildBSChart(data: FinancialResponse) {
  const km = data.key_metrics
  if (!km) return []

  return data.periods.map((p, i) => {
    const equity = toEok(metricValue(km["자본총계"], i))
    const liab = toEok(metricValue(km["부채총계"], i))
    const assets = metricValue(km["자산총계"], i)
    const liabRaw = metricValue(km["부채총계"], i)
    const debtRatio = assets && liabRaw ? Math.round((liabRaw / assets) * 1000) / 10 : null
    return { period: p, 자본총계: equity, 부채총계: liab, "부채비율(%)": debtRatio }
  })
}

export function buildCFChart(data: FinancialResponse) {
  const km = data.key_metrics
  if (!km) return []

  return data.periods.map((p, i) => ({
    period: p,
    영업활동: toEok(metricValue(km["영업활동현금흐름"], i)),
    투자활동: toEok(metricValue(km["투자활동현금흐름"], i)),
    재무활동: toEok(metricValue(km["재무활동현금흐름"], i)),
  }))
}
