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
  value: Company | null
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
  const { data: results = [] } = useCompanySearch(query)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "justify-between font-normal",
            !value && "text-muted-foreground",
            className
          )}
        >
          {value ? `${value.corp_name} (${value.stock_code})` : placeholder}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="p-0 w-[320px]" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={placeholder}
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>검색 결과가 없습니다</CommandEmpty>
            <CommandGroup>
              {results.map((c) => (
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
