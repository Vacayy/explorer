# 화면 기획서: 요약 페이지 (Resizable 패널 레이아웃)

> 경로: `/analyze/:stockCode/summary`
> 상태: 재설계, 구현 대기

---

## 1. 목적

기업의 핵심 정보를 **스크롤 없이 한 화면**에서 파악한다.
Resizable 패널로 사용자가 관심 영역의 크기를 자유롭게 조절.

---

## 2. 레이아웃

```
┌─────────────────────────────────────────────┐
│ KPI 스트립 (고정, resizable 밖)               │
│ 현재가 ▲3.2% │ 시총 2,388억 │ PER 7.9 │ ... │
├─────────────────────────────────────────────┤  ← vertical resizable
│ 주가 캔들스틱 + 거래량 (기본 40%)              │
│                                             │
├─────────────────────────────────────────────┤
│ 하단 3패널 (기본 60%)                        │
│ ┌───────────┬──────────────┬──────────────┐ │  ← horizontal resizable
│ │ 실적 차트   │ 실적 테이블    │ 공시 + 메모   │ │
│ │ (기본 35%) │ (기본 35%)   │ (기본 30%)   │ │
│ │            │              │              │ │
│ │ 매출+영익   │ 연도별 요약    │ 최근 공시 5건  │ │
│ │ +OPM      │ (스크롤)      │ ──────────── │ │
│ │            │              │ 최근 메모 3건  │ │
│ └───────────┴──────────────┴──────────────┘ │
└─────────────────────────────────────────────┘
```

### 패널 구조 (shadcn Resizable)

```tsx
<div> {/* KPI 스트립 — resizable 밖 */}
  <ResizablePanelGroup direction="vertical">
    <ResizablePanel defaultSize={40} minSize={25}>
      {/* 캔들스틱 차트 */}
    </ResizablePanel>
    <ResizableHandle withHandle />
    <ResizablePanel defaultSize={60} minSize={30}>
      <ResizablePanelGroup direction="horizontal">
        <ResizablePanel defaultSize={35} minSize={20}>
          {/* 실적 차트 */}
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={35} minSize={20}>
          {/* 실적 테이블 */}
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={30} minSize={15}>
          {/* 공시 + 메모 */}
        </ResizablePanel>
      </ResizablePanelGroup>
    </ResizablePanel>
  </ResizablePanelGroup>
</div>
```

---

## 3. 패널별 상세

### 3-1. KPI 스트립 (고정 상단)
- 기존 HeroKpiCards 대신 **인라인 수평 스트립**
- 높이: 1줄 (~40px)
- 내용: 현재가(변동률) │ 시가총액 │ PER │ PBR │ 영업이익률(변동%p) │ ROE(변동%p)
- 구분자: Separator (vertical)
- 데이터: useKpi hook

### 3-2. 캔들스틱 패널 (상단)
- CandlestickChart 컴포넌트 (lightweight-charts)
- 거래량 히스토그램 포함
- 높이: 패널 높이에 맞게 자동 조절 (ResizeObserver 이미 구현됨)
- 데이터: useStockPrices hook (5년)

### 3-3. 실적 차트 패널 (하단 좌)
- ComposedChart: 매출액(bar) + 영업이익(bar) + OPM%(line)
- 연도별, 최근 10년
- Recharts (기존 유지)
- ScrollArea로 감싸서 패널이 작아져도 차트가 잘리지 않게

### 3-4. 실적 테이블 패널 (하단 중)
- 기존 DataTable: 매출액/영업이익/당기순이익 + YoY
- 분기 미니테이블 (최근 4분기)
- ScrollArea로 세로 스크롤

### 3-5. 공시 + 메모 패널 (하단 우)
- 상단: 최근 공시 5건 (날짜 + 보고서명 + DART 링크)
- 하단: 최근 투자메모 3건 (Bull/Bear 아이콘 + 내용)
- Separator로 구분
- ScrollArea로 세로 스크롤

---

## 4. 상태별 정책

| 상태 | 동작 |
|------|------|
| KPI 로딩 | 인라인 Skeleton (높이 40px) |
| 캔들스틱 로딩 | 패널 내 Skeleton |
| 차트/테이블 로딩 | 각 패널 내 독립 Skeleton (Partial state) |
| 에러 | 해당 패널만 ErrorState 표시, 다른 패널은 정상 |
| 데이터 없음 | 해당 패널만 EmptyState |

---

## 5. 전체 높이 정책

- 전체 레이아웃: `calc(100vh - 헤더 - 네비게이션)` → 스크롤 없는 풀스크린
- 패널 최소 크기로 콘텐츠 잘림 방지
- 각 패널 내부는 ScrollArea로 overflow 처리
