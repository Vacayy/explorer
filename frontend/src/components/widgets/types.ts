import type { ComponentType } from "react"
import type { SectionKey } from "@/components/layout/navConfig"
import type { SizeSpec } from "./layout"

/** 위젯 본문이 받는 현재 크기(격자 칸) — 작으면 큰 숫자·한 줄만 */
export interface WidgetBodyProps { w: number; h: number }
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
  useMeta: () => WidgetMeta
  Body: ComponentType<WidgetBodyProps>
}
