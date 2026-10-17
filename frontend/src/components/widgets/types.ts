import type { ComponentType } from "react"
import type { SectionKey } from "@/components/layout/navConfig"

/** 기본 크기(12칸 폭 · 72px 행 기준 높이)와 최소값 — 대시보드가 10px 행으로 바꿔 쓴다 */
export interface SizeSpec { w: number; h: number; minW: number; minH: number }

/** 위젯 본문이 받는 현재 크기(격자 칸) — 작으면 큰 숫자·한 줄만 */
export interface WidgetBodyProps { w: number; h: number; params?: Record<string, unknown> }
/** 머리에 보일 원천 기준 시각과 고장 여부 */
export interface WidgetMeta { asOf: string | null; stale?: boolean }

/** 위젯 정의 (docs/specs/home-widgets.md §2) */
export interface WidgetDef {
  id: string
  title: string
  description: string
  section: SectionKey
  group: string
  size: SizeSpec
  /** 띠형(높이 1) — 평소엔 머리 없이 */
  flat?: boolean
  detailPath?: string
  /** 본문을 누르면 띄우는 상세 — 원래 화면과 같은 수준의 카드 (?widget=<id>) */
  Detail?: ComponentType
  useMeta: () => WidgetMeta
  Body: ComponentType<WidgetBodyProps>
}
