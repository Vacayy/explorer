import { Badge } from "@/components/ui/badge"
import { ROLE_LABEL, roleOrg } from "@/lib/person"
import type { PersonRole } from "@/types"

/** 역할 칩(정책·경영자·구루, 자동 분류) — org면 옆에 소속·직함 한 줄. 역할을 못 정한 사람은 그리지 않는다 */
export function RoleChip({ role, org = false }: { role: PersonRole | null; org?: boolean }) {
  if (!role) return null
  const o = org ? roleOrg(role) : null
  return <span className="inline-flex items-center gap-1.5">
    <Badge variant="outline" className="h-5 rounded-none px-1.5 text-[11px] font-normal" data-role={role.role}>{ROLE_LABEL[role.role]}</Badge>
    {o && <span className="text-caption text-muted-foreground">{o}</span>}
  </span>
}

