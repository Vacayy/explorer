import type { ComponentType } from "react"

/** 섹션 본문이 받는 밀도(옛 격자 칸 기준 w·h) — 작으면 큰 숫자·한 줄만 */
export interface WidgetBodyProps { w: number; h: number; params?: Record<string, unknown> }
/** 머리에 보일 원천 기준 시각과 고장 여부 */
export interface WidgetMeta { asOf: string | null; stale?: boolean }

/** 홈 고정 탭 섹션 정의 — home/HomeSection이 id로 본문·기준 시각·전체 보기 경로를 빌려 쓴다 */
export interface WidgetDef {
  id: string
  title: string
  /** 머리 ⓘ 툴팁 */
  description: string
  detailPath?: string
  useMeta: (params?: Record<string, unknown>) => WidgetMeta
  Body: ComponentType<WidgetBodyProps>
}
