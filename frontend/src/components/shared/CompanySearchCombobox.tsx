import { useState } from "react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from "@/components/ui/command"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useCompanySearch } from "@/hooks/useCompanySearch"
import type { Company } from "@/types"

interface Props {
  value: Pick<Company, 'corp_name' | 'stock_code'> | null
  onSelect: (company: Company) => void
  placeholder?: string
  className?: string
}

export default function CompanySearchCombobox({
  value,
  onSelect,
  placeholder = "종목 검색...",
  className,
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const { data: results = [], isFetching, isError, refetch } = useCompanySearch(query)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-label={value ? `${value.corp_name} (${value.stock_code})` : placeholder}
          title={value ? `${value.corp_name} (${value.stock_code})` : undefined}
          aria-expanded={open}
          className={cn(
            "justify-between font-normal",
            !value && "text-muted-foreground",
            className
          )}
        >
          <span className="truncate">{value ? `${value.corp_name} (${value.stock_code})` : placeholder}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[320px] max-w-[calc(100vw-2rem)] p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            aria-label={placeholder}
            placeholder={placeholder}
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            {isError ? <div role="alert" className="space-y-2 p-3 text-sm"><p>종목 검색을 불러오지 못했습니다.</p><Button variant="outline" size="sm" onClick={() => void refetch()}>다시 시도</Button></div> : isFetching ? <p role="status" className="p-3 text-sm text-muted-foreground">종목을 찾고 있습니다.</p> : <CommandEmpty>{query ? '검색 결과가 없습니다' : '종목 이름이나 코드를 입력하세요'}</CommandEmpty>}
            <CommandGroup>
              {!isFetching && !isError && results.map((c) => (
                <CommandItem
                  key={c.corp_code}
                  value={c.stock_code ?? ""}
                  onSelect={() => {
                    onSelect(c)
                    setOpen(false)
                    setQuery("")
                  }}
                >
                  <span className="font-medium">{c.corp_name}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {c.stock_code}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
