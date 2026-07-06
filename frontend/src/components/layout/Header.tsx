import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import { addToHistory } from "@/components/layout/SearchHistory"
import { Badge } from "@/components/ui/badge"
import ThemeToggle from "@/components/shared/ThemeToggle"
import {
  Command,
  CommandInput,
  CommandList,
  CommandGroup,
  CommandItem,
} from "@/components/ui/command"
import type { Company } from "@/types"

interface Props {
  selectedCompany: Company | null
}

export default function Header({ selectedCompany }: Props) {
  const navigate = useNavigate()
  const [query, setQuery] = useState("")
  const { data: results = [] } = useCompanySearch(query)

  return (
    <header className="sticky top-0 z-50 border-b bg-card">
      <div className="mx-auto max-w-[1440px] flex items-center gap-4 px-6 h-12">
        <h1 className="text-lg font-bold whitespace-nowrap">Stock Explorer</h1>

        <div className="relative w-[360px]">
          <Command shouldFilter={false} className="rounded-lg border shadow-none bg-transparent">
            <CommandInput
              placeholder="기업명 또는 종목코드 검색..."
              value={query}
              onValueChange={setQuery}
              data-search-input
            />
            {query.length > 0 && results.length > 0 && (
              <CommandList className="absolute top-full left-0 right-0 mt-1 z-50 rounded-lg border bg-popover shadow-lg max-h-[300px]">
                <CommandGroup>
                  {results.map((c) => (
                    <CommandItem
                      key={c.corp_code}
                      value={c.stock_code ?? ""}
                      onSelect={() => {
                        addToHistory(c)
                        setQuery("")
                        if (c.stock_code) navigate(`/analyze/${c.stock_code}/summary`)
                      }}
                    >
                      <span className="font-medium text-sm">{c.corp_name}</span>
                      <span className="ml-auto text-muted-foreground text-xs">{c.stock_code}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            )}
          </Command>
        </div>

        {selectedCompany && (
          <Badge variant="accent" className="text-sm font-medium">
            {selectedCompany.corp_name} ({selectedCompany.stock_code})
          </Badge>
        )}

        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
