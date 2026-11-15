import { RiskTiles } from '@/components/home/RiskTiles'
import { Link } from 'react-router-dom'
import { MiniSpark, fmtValue } from '@/components/home/MacroLiquidity'
import { PageContainer } from '@/components/shared/PageContainer'
import { QueryState } from '@/components/shared/QueryState'
import { usePublicMacro } from '@/hooks/usePublicMacro'
import { formatNumber, formatPercent } from '@/utils/format'
import type { PublicMacroCoverage, PublicMacroIndicator } from '@/types'

const COVERAGE: Record<PublicMacroCoverage['status'], string> = {
  available: '저장 자료 조회 가능',
  missing: '저장된 관측값 없음',
  source_review_pending: '출처·공개 범위 검토 중',
  invalid: '저장 자료 검증 필요',
}

function Indicator({ item }: { item: PublicMacroIndicator }) {
  const start = item.dated_series.at(0)?.[0]
  return <section aria-label={item.label} className="min-w-0 space-y-3 border p-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <div><p className="text-caption text-ink-3">{item.group_label}</p><h2 className="text-section font-semibold">{item.label}</h2></div>
      <p className="font-mono text-xl tabular-nums">{fmtValue(item)}</p>
    </div>
    <p className="text-sm text-ink-2">관측일 {item.as_of}</p>
    {item.series.length >= 2 ? <figure className="min-w-0 space-y-2" aria-label={`${item.label} 저장 관측 추이`}>
      <MiniSpark data={item.series} />
      <figcaption className="text-caption text-ink-3">{start ?? '-'} ~ {item.as_of} · {formatNumber(item.dated_series.length)}개 관측 · 관측 순서대로 표시</figcaption>
    </figure> : <p className="text-sm text-ink-3">추이를 표시할 관측값이 부족합니다.</p>}
    <div className="space-y-1 border-t pt-3">
      <p className="text-sm">{formatNumber(item.comparison_observations)}개 관측 전 대비 <span className="font-mono tabular-nums">{formatPercent(item.change_pct, 2)}</span></p>
      <p className="text-caption text-ink-3">비교 관측일 {item.comparison_date ?? '자료 부족'} · 달력상 {formatNumber(item.comparison_observations)}일 전을 뜻하지 않습니다.</p>
      {item.change_pct == null && <p className="text-caption text-ink-3">관측 수 또는 비교 기준값이 부족해 변화율을 표시하지 않습니다.</p>}
    </div>
    {item.key === 'net_liq' && <div className="space-y-1 border-t pt-3 text-caption text-ink-3">
      <p>순유동성 = 연준 총자산(WALCL) − 재무부 일반계정(TGA) − 익일물 역레포(RRP). Explorer가 계산한 참고값이며 원기관의 공식 지표가 아닙니다.</p>
      <p>관측일 사이에는 직전 값을 유지해 계산합니다. 연준 총자산은 수요일 잔액, TGA는 주평균, RRP는 일별 관측값이므로 같은 날의 잔액만 비교한 값이 아닙니다.</p>
    </div>}
    <ul aria-label={`${item.label} 원천`} className="space-y-1 text-caption text-ink-3">{item.sources.map(source => <li key={source.series_id} className="break-words">
      <a href={source.url} target="_blank" rel="noopener noreferrer" className="underline">{source.publisher} · {source.series_id}</a>
      <span> · 원천 관측일 {source.as_of ?? '미확인'}</span>
    </li>)}</ul>
  </section>
}

export function PublicMacroPage() {
  const query = usePublicMacro()
  return <PageContainer>
    <nav aria-label="위치" className="text-sm text-ink-3"><Link to="/home/kr">한국 시장</Link> · <Link to="/home/us">미국 시장</Link> › 매크로</nav>
    <h1 className="font-display text-page font-normal">매크로·유동성</h1>
    <p className="text-sm text-ink-2">지표마다 관측 주기와 최신 날짜가 다릅니다. 각 지표와 원천의 날짜를 확인해 주세요. 실시간 자료가 아닙니다.</p>
    <QueryState query={query} emptyMessage="표시할 매크로 자료가 없습니다.">{data => <>
      {data.items.length > 0 ? <div className="surface-grid grid min-w-0 md:grid-cols-2">{data.items.map(item => <Indicator key={item.key} item={item} />)}</div>
        : <p role="status" className="border p-4 text-sm text-ink-3">현재 표시할 공개 관측값이 없습니다. 아래 지표별 상태를 확인해 주세요.</p>}
      <section aria-label="지표별 제공 상태" className="space-y-2">
        <h2 className="text-section font-semibold">지표별 제공 상태</h2>
        <ul className="grid gap-x-6 sm:grid-cols-2">{data.coverage.map(item => <li key={item.key} className="flex min-w-0 flex-wrap justify-between gap-x-3 gap-y-1 border-b py-2 text-sm">
          <span>{item.label}</span><span className="text-ink-3">{COVERAGE[item.status]}</span>
        </li>)}</ul>
        {data.coverage.some(item => item.status === 'source_review_pending') && <p className="text-caption text-ink-3">출처 검토 중인 지표는 데이터가 없다는 뜻이 아닙니다. 공개할 수 있는 출처와 제공 범위를 확인하고 있습니다.</p>}
      </section>
      {data.items.some(item => item.sources.some(source => source.publisher === 'Federal Reserve Bank of New York')) &&
        <div className="space-y-1 text-caption text-ink-3">
          <p>© 2026 Federal Reserve Bank of New York. Content from the New York Fed subject to the Terms of Use at newyorkfed.org.</p>
          <p><a href="https://www.newyorkfed.org/privacy/termsofuse" target="_blank" rel="noopener noreferrer" className="underline">Federal Reserve Bank of New York 데이터 이용 조건</a></p>
          <p>Explorer의 계산·표시는 원기관의 보증을 뜻하지 않습니다.</p>
        </div>}
      <p className="text-sm text-ink-3">시장 국면·해설은 공개 화면 연결을 준비 중입니다.</p>
    </>}</QueryState>
    <RiskTiles showOverlay={false} />
  </PageContainer>
}
