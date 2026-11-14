import { useMemo, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { BlockHead } from '@/components/home/HomeSection'
import { Seg } from "@/components/home/MarketFrame"
import { FillArea } from "@/components/shared/Bounded"
import { PeerPerformanceBody, PeerResearchBody } from '@/components/peers/PeerBodies'
import { Button } from '@/components/ui/button'
import { PEER_DAYS, companyEvidence, peerDays, peerGroupSummary, peerMemberRows, peerView, selectPeerGroup, switchPeerView } from '@/lib/peerFrame'
import { formatPercent, formatPp } from '@/utils/format'
import type { PeerCatalog, PeerRuntime } from '@/types/peer'

const tone = (value: number | null | undefined) => value == null ? 'text-muted-foreground' : value > 0 ? 'text-up-ink' : value < 0 ? 'text-down-ink' : ''
const shortDate = (iso: string | null) => iso ? iso.slice(5).replace('-', '/') : '-'

/**
 * Peer 그룹 본문 (ia-redesign §4.12 계약 · §4.35 섹터 화면 Peer 탭, 옛 탐색 › Peer 그룹 PeerCatalogPage의 몸통).
 * 머리(그룹 이름 · 묶은 기준 ⓘ · 성과 비교 | 사업 근거) → 위치(섹터 › 상위 그룹 › 그룹) + 기간 → 칸 안 스크롤: 요약 띠 · 선택한 종목 띠 · 본문.
 * URL = view · group · stock · days. 보기를 바꿔도 group·stock·days는 그대로, 그룹을 바꾸면 stock을 지운다.
 */
export function PeerGroupPanel({ data, groupId, path }: { data: PeerRuntime; groupId: string; path: { id: string | null; name: string }[] }) {
  const { catalog, prices } = data
  const [params, setParams] = useSearchParams()
  const view = peerView(params)
  const days = peerDays(params)
  const group = catalog.groups.find(item => item.id === groupId)
  const rows = useMemo(() => group ? peerMemberRows(catalog, prices, group.id, days) : [], [catalog, prices, group, days])
  const summary = useMemo(() => group ? peerGroupSummary(catalog, prices, group.id) : null, [catalog, prices, group])
  const requested = params.get('stock')
  const selected = requested ? rows.find(row => row.code === requested) ?? null : rows.find(row => row.rank !== null) ?? rows[0] ?? null
  const missingStock = !!requested && !!group && !selected
  const pick = (id: string) => setParams(previous => selectPeerGroup(previous, id))
  const setView = (next: string, stock?: string) => setParams(previous => switchPeerView(previous, next === 'research' ? 'research' : 'performance', stock))
  const selectStock = (code: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set('stock', code); return next }, { replace: true, preventScrollReset: true })
  const setDays = (value: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set('days', value); return next }, { replace: true, preventScrollReset: true })
  const stale = data.lastAttempt?.status === 'error' || data.snapshotAgeHours > 72
  if (!group) return null
  return <>
    <BlockHead section title={group.name} info={group.interpretation} sub={`${rows.length}사 · 시작 = 100, ${days}거래일`}
      actions={<Seg label="보기" value={view} items={[{ key: 'performance', label: '성과 비교' }, { key: 'research', label: '사업 근거' }]} onChange={value => setView(value)} />} />
    <div className="flex shrink-0 flex-wrap items-center gap-1.5">
      <span className="text-xs text-ink-3">위치</span>
      <nav aria-label="그룹 위치" className="flex min-w-0 flex-wrap items-center gap-1 text-[12.5px]">
        {path.map((p, i) => <span key={`${p.id}-${i}`} className="flex items-center gap-1">
          {i > 0 && <span aria-hidden className="text-ink-3">›</span>}
          {i === path.length - 1 ? <b aria-current="page" className="font-semibold">{p.name}</b>
            : p.id ? <button type="button" className="hover:underline" onClick={() => pick(p.id!)}>{p.name}</button> : <span>{p.name}</span>}
        </span>)}
      </nav>
      <span className="ml-auto"><Seg label="기간" value={String(days)} items={PEER_DAYS.map(d => ({ key: String(d), label: `${d}일` }))} onChange={setDays} /></span>
    </div>
    <FillArea aria-label={`${group.name} 본문`}>
      <div className="space-y-3 pb-1">
        {stale && <p role="status" className="text-caption text-chart-warning">{data.lastAttempt?.status === 'error' ? `마지막 수집에 실패해 ${prices.asOf} 가격으로 보여 드립니다.` : `가격이 ${prices.asOf} 이후 갱신되지 않았습니다.`}</p>}
        {summary && <SummaryStrip summary={summary} />}
        {missingStock ? <p role="status" className="border bg-muted/40 p-3 text-sm">선택한 종목이 이 그룹에 없습니다. 목록에서 종목을 다시 골라 주세요.</p>
          : selected && <SelectedBand view={view} row={selected} catalog={catalog} rows={rows} days={days} onOther={() => setView(view === 'research' ? 'performance' : 'research', selected.code)} />}
        {view === 'research'
          ? <PeerResearchBody catalog={catalog} group={group} rows={rows} days={days} selected={selected?.code ?? null} onSelect={selectStock} onPick={pick} onPerformance={code => setView('performance', code)} />
          : <PeerPerformanceBody bare data={data} group={group} rows={rows} days={days} onDays={setDays} selected={selected?.code ?? null} onSelect={selectStock} onResearch={code => setView('research', code)} onPick={pick} />}
      </div>
    </FillArea>
  </>
}

function Cell({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return <div className="min-w-0 space-y-0.5 bg-card px-4 py-3"><p className="text-caption text-ink-3">{label}</p><p className="font-display text-[22px] leading-tight tabular-nums max-md:text-lg">{children}</p>{sub && <p className="text-caption text-ink-2">{sub}</p>}</div>
}

function SummaryStrip({ summary }: { summary: NonNullable<ReturnType<typeof peerGroupSummary>> }) {
  const partial = summary.covered < summary.memberCount
  return <section aria-label="그룹 요약" className="grid grid-cols-2 divide-x divide-y border md:grid-cols-4 md:divide-y-0 [&>*:nth-child(2)]:max-md:border-r-0">
    <div className="max-md:order-3"><Cell label="구성" sub={<>{summary.scope === 'product' ? '제품·공정 그룹' : '밸류체인'}{summary.parent && <span className="max-md:hidden"> · 상위 업종 {summary.parent.name}</span>}</>}>{summary.memberCount}사</Cell></div>
    <div className="max-md:order-1"><Cell label={`그룹 평균 · 60일${partial ? ` · ${summary.covered}/${summary.memberCount}사` : ''}`} sub={<>20일 <span className={tone(summary.avg[20])}>{formatPercent(summary.avg[20])}</span> · 5일 <span className={tone(summary.avg[5])}>{formatPercent(summary.avg[5])}</span></>}><span className={tone(summary.avg[60])}>{formatPercent(summary.avg[60])}</span></Cell></div>
    <div className="max-md:order-2"><Cell label="업종 대비 · 20일" sub={summary.parent ? <>{summary.parent.name} {summary.parent.memberCount}사 평균 {formatPercent(summary.parent.avg20)}</> : '상위 업종 없음'}><span className={tone(summary.vsParent20)}>{formatPp(summary.vsParent20, 1)}</span></Cell></div>
    <div className="max-md:order-4"><Cell label="사업 근거" sub={`주의 ${summary.caveats}건 · 마지막 확인 ${shortDate(summary.lastChecked)}`}>{summary.verifiedCompanies}/{summary.memberCount} 원문 확인</Cell></div>
  </section>
}

/** 선택한 종목 띠 — 반대쪽 보기를 요약하고 그 보기로 넘어가는 버튼을 단다 */
function SelectedBand({ view, row, catalog, rows, days, onOther }: { view: string; row: ReturnType<typeof peerMemberRows>[number]; catalog: PeerCatalog; rows: ReturnType<typeof peerMemberRows>; days: number; onOther: () => void }) {
  const company = catalog.companies.find(item => item.code === row.code)
  const evidence = company ? companyEvidence(company) : null
  return <section aria-label="선택한 종목" className="flex flex-wrap items-center gap-x-4 gap-y-2 border bg-surface-2 px-4 py-3 max-md:flex-col max-md:items-start">
    <span className="text-caption text-muted-foreground">선택한 종목</span>
    <span className="font-semibold">{row.name} <span className="font-mono text-caption font-normal text-muted-foreground">{row.code}</span></span>
    <span className="min-w-0 flex-1 text-sm max-md:w-full">
      {view === 'research'
        ? row.rank === null ? '가격 없음 · 순위 없음' : <>그룹 내 {row.rank}위 · {days}일 <span className={tone(row.returns[days as 5])}>{formatPercent(row.returns[days as 5])}</span> · Peer 대비 20일 <span className={tone(row.excess20)}>{formatPp(row.excess20, 1)}</span>{rows.length < 2 && ' · 단독'}</>
        : <>이 그룹에 넣은 근거 · {row.products.join('·')}{evidence && <> · {evidence.verified ? `원문 ${evidence.verified}` : '미확인'} · <span className={evidence.caveats ? 'text-chart-warning' : ''}>주의 {evidence.caveats}</span></>}</>}
    </span>
    <span className="flex gap-2 max-md:self-end">
      <Button asChild variant="outline" size="sm"><Link to={`/analyze/${row.code}/summary`}>도시에 ›</Link></Button>
      <Button size="sm" onClick={onOther}>{view === 'research' ? '성과 비교로 보기 ›' : '사업 근거 보기 ›'}</Button>
    </span>
  </section>
}
