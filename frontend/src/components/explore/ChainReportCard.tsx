import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/shared/ErrorState"
import { Markdown } from "@/components/shared/Markdown"
import { useChainPreview, useChainReport, useChainReports, useCreateChainReport } from "@/hooks/useTwRevenue"
import { formatKstDateTime, formatUsd } from "@/utils/format"
import type { ChainRef, ChainTreeNode } from "@/types"

/**
 * 트리 보고서(docs/specs/value-chain.md §16) — 고른 루트에서 공급 쪽으로 타고 들어가며 사실·기대·문서를 모은 자연어 보고서.
 * 버튼으로 요청할 때만 만든다. 루트 = 지도에서 고른 칸(URL node), 보고서 = URL report.
 */

const STATUS: Record<string, string> = { running: "만드는 중", done: "완료", partial: "일부 칸 빠짐", error: "실패" }

/** 본문 인용 [D123]·[W: URL]을 원문 링크로 — 컨콜 [C…]는 목록에서 확인 */
function linkify(body: string, refs: ChainRef[]) {
  const url = Object.fromEntries(refs.filter(r => r.url).map(r => [r.ref, r.url!]))
  return body
    .replace(/~/g, "\\~")                                // '1~4위 … 10~15%'가 GFM 취소선으로 그려지지 않게
    .replace(/\[(D\d+)\]/g, (m, k) => url[k] ? `[${k}](${url[k]})` : m)
    .replace(/\[W:\s*(https?:\/\/[^\]\s]+)\s*\]/g, (_, u) => `[웹](${u})`)
}

function Tree({ tree }: { tree: ChainTreeNode[] }) {
  return <ul className="space-y-0.5 text-caption">
    {tree.map(t => <li key={t.key} style={{ paddingLeft: t.depth * 16 }} className="tabular-nums">
      {t.depth ? "└ " : ""}<span className={t.depth ? "" : "font-semibold"}>{t.name}</span>
      {t.flow_usd ? <span className="text-muted-foreground"> · 추정 증가액 +{formatUsd(t.flow_usd)}</span> : null}
    </li>)}
  </ul>
}

export function ChainReportCard({ root, rootName, reportId, onReport }: {
  root: string; rootName: string; reportId: number | null; onReport: (id: number | null) => void
}) {
  const preview = useChainPreview(root)
  const list = useChainReports(root)
  const current = reportId ?? list.data?.[0]?.id ?? null
  const report = useChainReport(current)
  const create = useCreateChainReport()
  const r = report.data && report.data.root === root ? report.data : null
  const running = r?.status === "running" || create.isPending

  return <Card>
    <CardHeader className="pb-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-card-title">밸류체인 보고서 — {rootName}</CardTitle>
        <Button size="sm" disabled={running || preview.isLoading} onClick={() => create.mutate(root, { onSuccess: x => onReport(x.id) })}>
          {running ? "만드는 중…" : "보고서 만들기"}
        </Button>
      </div>
      <p className="text-caption text-muted-foreground">
        지도에서 고른 칸을 루트로, 공급 쪽으로 깊이 3·칸 12까지(추정 증가액이 큰 가지 우선) 타고 들어가며 사실·시장 기대·컨퍼런스콜·피드를 모아 씁니다.
        {preview.data && ` 칸 메모 ${preview.data.models.note} 최대 ${preview.data.calls.node_notes_max}회(자료가 그대로인 칸은 재사용) + 종합 ${preview.data.models.synthesis} 1회·웹 검색 최대 ${preview.data.calls.web_search_cap}회.`}
        {" "}출처 없는 문장은 쓰지 않고, 사실과 기대를 구분합니다. 버튼을 누를 때만 만듭니다.
      </p>
      {create.isError && <p className="text-caption text-destructive">보고서 요청에 실패했습니다.</p>}
    </CardHeader>
    <CardContent className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
      <div className="space-y-4">
        <div><p className="mb-1 text-caption font-medium text-muted-foreground">타고 들어갈 트리</p>
          {preview.isLoading ? <Skeleton className="h-40 w-full" /> : preview.isError ? <p className="text-caption text-destructive">트리를 불러오지 못했습니다.</p>
            : preview.data && <Tree tree={preview.data.tree} />}</div>
        {!!list.data?.length && <div><p className="mb-1 text-caption font-medium text-muted-foreground">이전 보고서</p>
          <ul className="space-y-0.5">{list.data.map(x => <li key={x.id}>
            <Button variant={x.id === current ? "secondary" : "ghost"} size="sm" onClick={() => onReport(x.id)} className="h-auto w-full justify-between px-2 py-1 text-caption font-normal">
              <span className="tabular-nums">{formatKstDateTime(x.created_at)}</span><span className="text-muted-foreground">{STATUS[x.status] ?? x.status}</span>
            </Button></li>)}</ul></div>}
      </div>
      <div className="min-w-0">
        {list.isLoading || (current != null && report.isLoading) ? <Skeleton className="h-64 w-full" />
          : report.isError ? <ErrorState message="보고서를 불러오지 못했습니다." onRetry={() => void report.refetch()} />
          : !r ? <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">아직 이 루트의 보고서가 없습니다. 왼쪽 트리를 확인하고 '보고서 만들기'를 누르세요.</div>
          : r.status === "running" ? <div className="space-y-2 rounded-lg border p-4 text-sm"><p className="font-medium">만드는 중 — {r.progress ?? "준비 중"}</p>
            <p className="text-caption text-muted-foreground">칸 메모를 쓰고 종합합니다. 몇 분 걸리며, 이 화면을 떠나도 계속 만들어집니다.</p><Skeleton className="h-40 w-full" /></div>
          : r.status === "error" ? <ErrorState message={`보고서를 만들지 못했습니다: ${r.error ?? "알 수 없는 오류"}`} onRetry={() => create.mutate(root, { onSuccess: x => onReport(x.id) })} />
          : <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
              <Badge variant={r.status === "done" ? "secondary" : "outline"}>{STATUS[r.status]}</Badge>
              <span className="tabular-nums">{formatKstDateTime(r.finished_at ?? r.created_at)}</span><span>· {r.model}</span>
              {r.missing.length > 0 && <span className="text-destructive">메모 실패로 빠진 칸: {r.missing.map(m => m.name).join(", ")}</span>}
            </div>
            <Markdown>{linkify(r.body ?? "", r.refs)}</Markdown>
            {r.refs.length > 0 && <div className="border-t pt-3">
              <p className="mb-1 text-caption font-medium text-muted-foreground">인용 가능한 자료 {r.refs.length}건</p>
              <ul className="grid gap-x-4 gap-y-0.5 text-caption sm:grid-cols-2">{r.refs.map(x => <li key={x.ref} className="truncate">
                <span className="tabular-nums text-muted-foreground">[{x.ref}]</span>{" "}
                {x.url ? <a href={x.url} target="_blank" rel="noreferrer" className="hover:underline">{x.title}</a> : x.title}
                <span className="text-muted-foreground"> · {x.date}</span>
              </li>)}</ul>
            </div>}
          </div>}
      </div>
    </CardContent>
  </Card>
}
