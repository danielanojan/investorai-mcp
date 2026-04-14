
import { useState, useEffect, useRef } from 'react'
import { Search } from 'lucide-react'
import { searchTickers } from '../api/stocks'
import type { Ticker } from '../types'

interface Props {
  onSelect: (ticker: Ticker) => void
  selected: Ticker | null
}

export default function TickerSelector({ onSelect, selected }: Props) {
  const [query, setQuery]     = useState('')
  const [results, setResults] = useState<Ticker[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen]       = useState(false)
  const debounceRef           = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const wrapperRef            = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!query.trim()) { setResults([]); return }
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const matches = await searchTickers(query)
        setResults(matches)
        setOpen(true)
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 300)
  }, [query])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node))
        setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleSelect = (ticker: Ticker) => {
    onSelect(ticker)
    setQuery('')
    setResults([])
    setOpen(false)
  }

  return (
    <div ref={wrapperRef} className="relative w-full max-w-md">
      <div className="flex items-center gap-2 border border-gray-300 rounded-lg px-3 py-2 bg-white shadow-sm focus-within:ring-2 focus-within:ring-blue-500">
        <Search size={16} className="text-gray-400 flex-shrink-0" />
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder={selected ? selected.symbol : "Search stocks..."}
          className="flex-1 outline-none text-sm text-gray-700 placeholder-gray-400"
        />
        {loading && (
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {selected && !query && (
        <div className="mt-2 flex items-center gap-2">
          <span className="inline-flex items-center gap-1 bg-blue-50 text-blue-700 text-sm font-medium px-3 py-1 rounded-full border border-blue-200">
            {selected.symbol}
            <span className="text-blue-400 font-normal">·</span>
            <span className="font-normal text-blue-600">{selected.name}</span>
          </span>
        </div>
      )}

      {open && results.length > 0 && (
        <div className="absolute z-50 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-y-auto">
          {results.map(ticker => (
            <button
              key={ticker.symbol}
              onClick={() => handleSelect(ticker)}
              className="w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between border-b border-gray-100 last:border-0"
            >
              <div>
                <span className="font-semibold text-gray-800 text-sm">{ticker.symbol}</span>
                <span className="ml-2 text-gray-500 text-sm">{ticker.name}</span>
              </div>
              <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
                {ticker.sector}
              </span>
            </button>
          ))}
        </div>
      )}

      {open && !loading && query && results.length === 0 && (
        <div className="absolute z-50 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg px-4 py-3 text-sm text-gray-500">
          No stocks found for "{query}"
        </div>
      )}
    </div>
  )
}
