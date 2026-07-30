import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { usDossierQuery, usMentionsQuery } from "@/api/spine"
import { PageContainer } from "@/components/shared/PageContainer"
import { ErrorState } from "@/components/shared/ErrorState"
import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { LensView } from "@/components/lens/LensPage"

const SRC_LABEL: Record<string, string> = {
  transcript: "컨콜", youtube: "유튜브", blog: "블로그", news: "뉴스", article: "아티클",
  telegram: "텔레그램", canon: "역사", note: "메모",
}

function usd(v?: number | null) {
  if (v == null) return "-"
  const a = Math.abs(v)
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `$${(v / 1e6).toFixed(0)}M`
  return `$${v.toLocaleString()}`
}
function num(v?: number | null, d = 1) {
  return v == null ? "-" : v.toFixed(d)
}

/**
 * 미국 종목 도시에 (docs/specs/us-dossier.md) — 경량 통합 뷰.
 * 헤더(yfinance 시세·밸류) + 투자 렌즈(가치/추세, market='us') + 컨콜·언급 링크.
 */
export default function UsDossierPage() {
  const { ticker = "" } = useParams<{ ticker: string }>()
  const q = useQuery(usDossierQuery(ticker))

  if (q.isLoading)
    return (
      <PageContainer>
        <Skeleton className="h-24 w-full rounded-xl" />
      </PageContainer>
    )
  if (q.isError || !q.data)
    return (
      <PageContainer>
        <ErrorState onRetry={() => q.refetch()} />
      </PageContainer>
    )

  const d = q.data
  const f = d.fundamentals
  const pt = (f?.estimates?.price_targets ?? null) as { mean?: number } | null
  const up = pt?.mean && f?.price ? ((pt.mean - f.price) / f.price) * 100 : null

  return (
    <PageContainer gap="sm">
      <Card>
        <CardContent className="py-4">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold">{d.name}</span>
            <span className="text-sm text-muted-foreground">{d.ticker}</span>
          </div>
          {f ? (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <span>
                현재가 <b>${num(f.price, 2)}</b>
              </span>
              <span className="text-muted-foreground">시총 {usd(f.market_cap)}</span>
              <span className="text-muted-foreground">Fwd PER {num(f.fwd_pe)}배</span>
              <span className="text-muted-foreground">trailing {num(f.trailing_pe)}배</span>
              {up != null && (
                <span className={up >= 0 ? "text-up" : "text-down"}>
                  목표가 대비 {up >= 0 ? "+" : ""}
                  {up.toFixed(0)}%
                </span>
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">시세 데이터를 불러오지 못했습니다.</p>
          )}
          <div className="mt-2 flex gap-3 text-xs">
            {d.latest_transcript && (
              <Link to="/follow/transcripts" className="text-primary hover:underline">
                최근 컨콜 {d.latest_transcript.fiscal_year} {d.latest_transcript.fiscal_period} →
              </Link>
            )}
            <Link to="/us" className="text-muted-foreground hover:underline">
              ← 미국 종목 목록
            </Link>
          </div>
        </CardContent>
      </Card>

      <LensView code={d.ticker} market="us" />

      <MentionsSection ticker={d.ticker} name={d.name} />
    </PageContainer>
  )
}

/** 여론 — 이 종목 언급 문서(entity_links). 컨콜·유튜브·인물·뉴스 혼합, US 소스는 Phase 3로 확충. */
function MentionsSection({ ticker, name }: { ticker: string; name: string }) {
  const q = useQuery(usMentionsQuery(ticker))
  const items = q.data ?? []
  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-semibold">여론 · 최근 언급 {items.length ? `(${items.length})` : ""}</span>
          <Link to={`/feed?q=${encodeURIComponent(name)}`} className="text-xs text-primary hover:underline">
            더 보기 →
          </Link>
        </div>
        {q.isLoading ? (
          <Skeleton className="mt-3 h-16 w-full rounded-lg" />
        ) : items.length === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">
            아직 이 종목을 언급한 수집 문서가 없습니다 — 컨콜·US 유튜브·인물 소스를 구독하면 채워집니다.
          </p>
        ) : (
          <ul className="mt-2 divide-y">
            {items.map((m) => (
              <li key={m.id} className="py-2">
                <Link to={`/doc/${m.id}`} className="flex items-start gap-2 group">
                  <Badge variant="secondary" className="text-[10px] font-normal shrink-0 mt-0.5">
                    {SRC_LABEL[m.source_type] ?? m.source_type}
                  </Badge>
                  <span className="min-w-0 flex-1">
                    <span className="text-sm group-hover:underline line-clamp-1">{m.title || m.excerpt || "(제목 없음)"}</span>
                    {m.published_at && (
                      <span className="block text-[10px] text-muted-foreground tabular-nums">
                        {m.published_at.slice(0, 10)}
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
