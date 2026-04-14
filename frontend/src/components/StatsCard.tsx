import type { DailySummary } from '../types'

interface Props {
  summary: DailySummary
}

function StatItem({ label, value, highlight }: {
  label: string
  value: string
  highlight?: 'positive' | 'negative' | 'neutral'
}) {
  const colour = highlight === 'positive' ? 'text-green-600'
               : highlight === 'negative' ? 'text-red-600'
               : 'text-gray-800'
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-gray-500 uppercase tracking-wide">{label}</span>
      <span className={`text-sm font-semibold ${colour}`}>{value}</span>
    </div>
  )
}

export default function StatsCard({ summary }: Props) {
  const returnHighlight = summary.period_return_pct >= 0 ? 'positive' : 'negative'
  const returnSign      = summary.period_return_pct >= 0 ? '+' : ''

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-bold text-gray-900">{summary.symbol}</h2>
          <p className="text-xs text-gray-500">{summary.range} performance</p>
        </div>
        <div className={`text-2xl font-bold ${returnHighlight === 'positive' ? 'text-green-600' : 'text-red-600'}`}>
          {returnSign}{summary.period_return_pct.toFixed(2)}%
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <StatItem label="Current"      value={`$${summary.end_price.toFixed(2)}`} />
        <StatItem label="Start"        value={`$${summary.start_price.toFixed(2)}`} />
        <StatItem label="52W High"     value={`$${summary.high_price.toFixed(2)}`}  highlight="positive" />
        <StatItem label="52W Low"      value={`$${summary.low_price.toFixed(2)}`}   highlight="negative" />
        <StatItem label="Avg Price"    value={`$${summary.avg_price.toFixed(2)}`} />
        <StatItem label="Volatility"   value={`${summary.volatality_pct.toFixed(1)}%`} />
        <StatItem label="Trading Days" value={summary.trading_days.toString()} />
        <StatItem label="Data"         value={summary.is_stale ? '⚠ Stale' : '✓ Fresh'} highlight={summary.is_stale ? 'negative' : 'positive'} />
      </div>
    </div>
  )
}
