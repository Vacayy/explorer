import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { formatDartAmount, formatPercent } from "@/utils/format"

interface FinancialTableProps {
  periods: string[]
  rows: {
    account_nm: string
    values: (string | null)[]
    yoy: (number | null)[]
  }[]
  unit?: string
  exportFilename?: string
}

function downloadCsv(
  periods: string[],
  rows: { account_nm: string; values: (string | null)[] }[],
  filename: string
) {
  const header = ["계정명", ...periods].join(",")
  const dataRows = rows.map((row) =>
    [row.account_nm, ...row.values.map((v) => v ?? "")].join(",")
  )
  const csv = [header, ...dataRows].join("\n")
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename + ".csv"
  a.click()
  URL.revokeObjectURL(url)
}

/** Financial data table — wraps shadcn Table for DART financial data display */
export default function DataTable({ periods, rows, unit = "(단위: 원)", exportFilename }: FinancialTableProps) {
  return (
    <div className="relative">
      {exportFilename && (
        <Button
          variant="ghost"
          size="xs"
          onClick={() => downloadCsv(periods, rows, exportFilename)}
          className="absolute top-0 right-0 z-10 text-muted-foreground hover:text-foreground"
        >
          CSV ↓
        </Button>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-left w-[180px]">{unit}</TableHead>
            {periods.map((p) => (
              <TableHead key={p} className="text-right min-w-[100px]">{p}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.account_nm}>
              <TableCell className="font-medium whitespace-nowrap">{row.account_nm}</TableCell>
              {row.values.map((v, i) => (
                <TableCell key={i} className="text-right whitespace-nowrap">
                  <div>{formatDartAmount(v)}</div>
                  {row.yoy[i] != null && (
                    <div className={cn(
                      "text-[11px]",
                      row.yoy[i]! > 0 ? "text-red-600" : row.yoy[i]! < 0 ? "text-blue-600" : "text-muted-foreground"
                    )}>
                      {row.yoy[i]! > 0 ? "▲" : row.yoy[i]! < 0 ? "▼" : ""}
                      {formatPercent(row.yoy[i])}
                    </div>
                  )}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
