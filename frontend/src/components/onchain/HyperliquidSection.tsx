import { memo } from "react"
import { useHyperliquid } from "@/hooks/useOnchain"
import type { HyperliquidAsset, HyperliquidStock } from "@/hooks/useOnchain"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { formatUsd, formatPrice, formatFundingRate } from "@/utils/format"
import { SectionSkeleton, ErrorCard } from "./SectionSkeleton"

const AssetRow = memo(function AssetRow({ asset }: { asset: HyperliquidAsset }) {
  const isPositive = asset.changePct >= 0
  return (
    <tr className="border-b last:border-b-0 hover:bg-muted/50">
      <td className="py-2.5 px-3 font-medium">{asset.name}</td>
      <td className="py-2.5 px-3 text-right font-mono">{formatPrice(asset.markPx)}</td>
      <td className={cn("py-2.5 px-3 text-right font-mono", isPositive ? "text-red-500" : "text-blue-500")}>
        {isPositive ? "+" : ""}{asset.changePct.toFixed(2)}%
      </td>
      <td className="py-2.5 px-3 text-right font-mono text-muted-foreground text-xs">
        {formatFundingRate(asset.funding)}
      </td>
      <td className="py-2.5 px-3 text-right font-mono text-muted-foreground text-xs">
        {formatUsd(asset.openInterest * asset.markPx)}
      </td>
      <td className="py-2.5 px-3 text-right font-mono text-muted-foreground text-xs">
        {formatUsd(asset.dayNtlVlm)}
      </td>
    </tr>
  )
})

const StockRow = memo(function StockRow({ stock }: { stock: HyperliquidStock }) {
  const isPositive = stock.changePct >= 0
  const price = stock.midPx ?? stock.markPx
  return (
    <tr className="border-b last:border-b-0 hover:bg-muted/50">
      <td className="py-2.5 px-3 font-medium">{stock.name}</td>
      <td className="py-2.5 px-3 text-right font-mono">
        {price != null ? formatPrice(price) : "-"}
      </td>
      <td className="py-2.5 px-3 text-right font-mono text-muted-foreground text-xs">
        {stock.markPx != null ? formatPrice(stock.markPx) : "-"}
      </td>
      <td className={cn("py-2.5 px-3 text-right font-mono", isPositive ? "text-red-500" : "text-blue-500")}>
        {stock.changePct !== 0 ? `${isPositive ? "+" : ""}${stock.changePct.toFixed(2)}%` : "-"}
      </td>
      <td className="py-2.5 px-3 text-right font-mono text-muted-foreground text-xs">
        {stock.dayNtlVlm > 0 ? formatUsd(stock.dayNtlVlm) : "-"}
      </td>
    </tr>
  )
})

export default function HyperliquidSection() {
  const { data, isLoading, error } = useHyperliquid()

  if (isLoading) return <SectionSkeleton title="Hyperliquid - Crypto Perpetuals" />
  if (error) return <ErrorCard title="Hyperliquid" message="데이터를 불러올 수 없습니다." />

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          Hyperliquid — Crypto Perpetuals
          <span className="text-xs font-normal text-muted-foreground">실시간 무기한 선물</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Featured assets */}
        <div className="mb-5">
          <div className="text-xs font-medium text-muted-foreground mb-2">주요 자산</div>
          <div className="grid grid-cols-5 gap-3">
            {data?.featured.map((asset) => {
              const isPositive = asset.changePct >= 0
              return (
                <div key={asset.name} className="rounded-lg border p-3">
                  <div className="text-sm font-semibold">{asset.name}</div>
                  <div className="text-lg font-mono mt-1">{formatPrice(asset.markPx)}</div>
                  <div className={cn("text-sm font-mono", isPositive ? "text-red-500" : "text-blue-500")}>
                    {isPositive ? "+" : ""}{asset.changePct.toFixed(2)}%
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Vol {formatUsd(asset.dayNtlVlm)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Top by volume table */}
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-2">거래량 상위 10 (무기한 선물)</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="py-2 px-3 text-left font-medium">자산</th>
                  <th className="py-2 px-3 text-right font-medium">가격</th>
                  <th className="py-2 px-3 text-right font-medium">24h 변동</th>
                  <th className="py-2 px-3 text-right font-medium">펀딩비</th>
                  <th className="py-2 px-3 text-right font-medium">미결제약정</th>
                  <th className="py-2 px-3 text-right font-medium">24h 거래량</th>
                </tr>
              </thead>
              <tbody>
                {data?.top_volume.map((asset) => (
                  <AssetRow key={asset.name} asset={asset} />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Tokenized stocks */}
        {data?.stocks && data.stocks.length > 0 && (
          <div className="mt-5">
            <div className="text-xs font-medium text-muted-foreground mb-2">
              토큰화 주식 (Spot)
              <span className="ml-1 font-normal">— 유동성이 낮을 수 있음</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="py-2 px-3 text-left font-medium">티커</th>
                    <th className="py-2 px-3 text-right font-medium">Mid 가격</th>
                    <th className="py-2 px-3 text-right font-medium">Mark 가격</th>
                    <th className="py-2 px-3 text-right font-medium">24h 변동</th>
                    <th className="py-2 px-3 text-right font-medium">24h 거래량</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stocks.map((s) => (
                    <StockRow key={s.name} stock={s} />
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 p-3 rounded-lg bg-muted/50 text-xs text-muted-foreground">
              SKHYNIX-USDC는 xyz 독립 배포 마켓으로 표준 API에서 조회 불가합니다.{" "}
              <a
                href="https://app.hyperliquid.xyz/trade/SKHYNIX-USDC"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                Hyperliquid에서 직접 보기
              </a>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
