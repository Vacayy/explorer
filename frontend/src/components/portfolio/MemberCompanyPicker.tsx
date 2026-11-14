import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem } from '@/components/ui/command'
import { useMemberPortfolioCompanies } from '@/hooks/useMemberPortfolio'
import type { PortfolioCompany } from '@/types'

export function MemberCompanyPicker({ value, onSelect, className }: {
  value: { stock_code: string | null; corp_name: string } | null
  onSelect: (company: PortfolioCompany) => void
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const query = useMemberPortfolioCompanies(open ? text : '')
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild><Button className={className} variant="outline" role="combobox" aria-expanded={open}>
      {value ? `${value.corp_name} (${value.stock_code})` : '종목 검색...'}
    </Button></PopoverTrigger>
    <PopoverContent className="w-80 max-w-[calc(100vw-2rem)] p-0" align="start">
      <Command shouldFilter={false}>
        <CommandInput aria-label="종목 이름이나 코드" placeholder="종목 이름이나 코드" value={text} onValueChange={setText} />
        <CommandList>
          {query.isError ? <div role="alert" className="p-3"><p>종목 검색을 불러오지 못했습니다.</p><Button onClick={() => void query.refetch()}>다시 시도</Button></div>
            : query.isFetching ? <p role="status" className="p-3">종목을 찾고 있습니다.</p>
            : <CommandEmpty>{text.trim() ? '검색 결과가 없습니다.' : '종목 이름이나 코드를 입력하세요.'}</CommandEmpty>}
          <CommandGroup>{!query.isFetching && !query.isError && query.data?.map(company => <CommandItem key={company.stock_code} value={company.stock_code}
            onSelect={() => { onSelect(company); setOpen(false); setText('') }}>
            {company.corp_name}<span className="ml-auto text-xs text-ink-2">{company.stock_code}</span>
          </CommandItem>)}</CommandGroup>
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>
}
