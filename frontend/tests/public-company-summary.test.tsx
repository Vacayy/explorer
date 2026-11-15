import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
const state = vi.hoisted(() => ({ prices: {} as Record<string, unknown>, calls: [] as unknown[][] }))
vi.mock('@/hooks/useCompanySearch', () => ({ useCompany: () => ready({corp_name:'Fixture',stock_code:'111111',market:'KOSPI',sector:'반도체'}) }))
vi.mock('@/hooks/usePublicCompanyPrices', () => ({ usePublicCompanyPrices: () => state.prices }))
vi.mock('@/hooks/useFinancials', () => ({ useFinancials: (...args: unknown[]) => { state.calls.push(args); return ready({periods:['25.03','26.03'],rows:[{account_nm:'매출액',values:['100','200'],yoy:[null,100]}],key_metrics:{},sj_div:'IS',fs_div:'CFS',period_type:'quarterly'}) } }))
vi.mock('@/components/charts/CandlestickChart', () => ({ default: ({data}: {data:unknown[]}) => <div data-testid="candles">{data.length}</div> }))
vi.mock('@/components/shared/NextQuestions', () => ({ default: () => { throw new Error('private questions mounted') } }))
vi.mock('@/components/company/CompanyOverview', () => ({ CompanyOverviewCard: () => { throw new Error('private profile mounted') } }))
import { PublicContent } from '@/components/auth/PublicContent'
function ready(data:unknown) { return {data,error:null,isPending:false,isFetching:false,fetchStatus:'idle',refetch:vi.fn()} }
function Location() { const l=useLocation(); return <output data-testid="location">{l.pathname}{l.search}</output> }
function setup() { state.calls=[];state.prices=ready({items:[{trade_date:'2026-01-02',open:10,high:12,low:9,close:11,volume:100,market_cap:10000}]}) }
function show(query='') { return render(<MemoryRouter initialEntries={['/analyze/111111/summary'+query]}><PublicContent/><Location/></MemoryRouter>) }
afterEach(() => {cleanup();vi.clearAllMocks()})
it('preserves sector/map and price range through financial navigation', () => {
 setup();const sectorQuery='?range=3m&map_query='+encodeURIComponent('?v=table&q=반도체');show('?'+new URLSearchParams({sector:'반도체·전자부품',sector_query:sectorQuery}))
 expect(screen.getByRole('heading',{name:'Fixture · 111111'})).toBeTruthy();expect(screen.getByTestId('candles').textContent).toBe('1')
 expect(state.calls.at(-1)?.at(-1)).toEqual({storedOnly:true})
 const back=screen.getByRole('link',{name:'반도체·전자부품 섹터로'}).getAttribute('href');expect(back).toBe('/industry/'+encodeURIComponent('반도체·전자부품')+sectorQuery)
 fireEvent.click(screen.getByRole('radio',{name:'1년'}));fireEvent.click(screen.getByRole('link',{name:'재무제표 보기 ›'}))
 expect(screen.getByTestId('location').textContent).toContain('/financials?summary_query=')
 fireEvent.click(screen.getByRole('link',{name:'기업 요약으로'}));expect(screen.getByTestId('location').textContent).toContain('price_range=1y')
 expect(screen.getByRole('link',{name:'반도체·전자부품 섹터로'}).getAttribute('href')).toBe(back)
})
it('distinguishes incomplete and empty prices without inventing candles', () => {
 setup();state.prices=ready({items:[{trade_date:'2026-01-02',open:null,high:12,low:9,close:11,volume:null,market_cap:null}]});const partial=show()
 expect(screen.getByText(/일부 시세가 없어/)).toBeTruthy();expect(screen.queryByTestId('candles')).toBeNull();partial.unmount()
 state.prices=ready({items:[]});show();expect(screen.getByText('저장된 시세가 없습니다.')).toBeTruthy()
})
it('supports loading and retry', () => {
 setup();state.prices={...ready(undefined),isPending:true,fetchStatus:'fetching'};const loading=show();expect(screen.getByRole('status',{name:'데이터 불러오는 중'})).toBeTruthy();loading.unmount()
 const retry=vi.fn();state.prices={...ready(undefined),error:new Error('fixture'),refetch:retry};show();fireEvent.click(screen.getByRole('button',{name:/다시|재시도/}));expect(retry).toHaveBeenCalledOnce()
})
