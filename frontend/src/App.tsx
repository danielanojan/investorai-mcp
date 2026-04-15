import { useState } from 'react'
import { useQuery, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TickerSelector from './components/TickerSelector'
import StatsCard from './components/StatsCard'
import PriceChart from './components/PriceChart'
import NewsFeed from './components/NewsFeed'
import ChatPanel from './components/ChatPanel'
import MonitoringDashboard from './components/MonitoringDashboard'
import { getDailySummary, getPriceHistory, getNews } from './api/stocks'
import type { Ticker, TimeRange } from './types'

const queryClient = new QueryClient()
const RANGES: TimeRange[] = ['1W', '1M', '3M', '6M', '1Y', '3Y', '5Y']

function Dashboard() {
  const [selected, setSelected] = useState<Ticker | null>(null)
  const [range, setRange]       = useState<TimeRange>('1Y')

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['summary', selected?.symbol, range],
    queryFn:  () => getDailySummary(selected!.symbol, range),
    enabled:  !!selected,
  })

  const { data: prices, isLoading: pricesLoading } = useQuery({
    queryKey: ['prices', selected?.symbol, range],
    queryFn:  () => getPriceHistory(selected!.symbol, range),
    enabled:  !!selected,
  })

  const { data: news, isLoading: newsLoading } = useQuery({
    queryKey: ['news', selected?.symbol],
    queryFn:  () => getNews(selected!.symbol, 10),
    enabled:  !!selected,
  })

  const isLoading = summaryLoading || pricesLoading || newsLoading

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">InvestorAI</h1>
            <p className="text-xs text-gray-500">Stock research for everyone</p>
          </div>
          <TickerSelector selected={selected} onSelect={setSelected} />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6">
        {!selected && (
          <div className="text-center py-20 text-gray-400">
            <p className="text-lg">Search for a stock to get started</p>
            <p className="text-sm mt-1">
              Try "Apple", "TSLA", or "semiconductor"
            </p>
          </div>
        )}

        {selected && (
          <div className="space-y-6">
            <div className="flex gap-2">
              {RANGES.map(r => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={`px-3 py-1.5 text-sm rounded-lg font-medium transition-colors ${
                    range === r
                      ? 'bg-blue-600 text-white'
                      : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>

            {isLoading && (
              <div className="bg-white rounded-xl border border-gray-200 p-6 text-center text-gray-400 text-sm">
                Loading...
              </div>
            )}

            {!isLoading && (
              <>
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <div className="lg:col-span-2 space-y-6">
                    {summary && <StatsCard summary={summary} />}
                    {prices   && <PriceChart data={prices} />}
                  </div>
                  <div className="lg:col-span-1">
                    <NewsFeed articles={news || []} symbol={selected.symbol} />
                  </div>
                </div>
                <ChatPanel symbol={selected.symbol} range={range} />
              </>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

function AppRouter() {
  const isPlayground = window.location.pathname === '/playground'
  return isPlayground ? <MonitoringDashboard /> : <Dashboard />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppRouter />
    </QueryClientProvider>
  )
}
