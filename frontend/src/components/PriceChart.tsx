import { useMemo } from 'react'
import {
  ResponsiveContainer, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts'
import type { PriceHistory, PricePoint } from '../types'

interface Props {
  data: PriceHistory
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function formatPrice(value: number): string {
  return `$${value.toFixed(2)}`
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-sm">
      <p className="text-gray-500 text-xs mb-1">{label}</p>
      <p className="font-semibold text-gray-900">{formatPrice(payload[0].value)}</p>
    </div>
  )
}

export default function PriceChart({ data }: Props) {
  const isPositive = data.period_return_pct >= 0
  const colour     = isPositive ? '#16a34a' : '#dc2626'
  const fillId     = `gradient-${data.symbol}`

  // Sample data points for performance — max 252 points
  const chartData = useMemo(() => {
    const prices = data.prices
    if (prices.length <= 252) return prices
    const step = Math.ceil(prices.length / 252)
    return prices.filter((_: PricePoint, i: number) => i % step === 0)
  }, [data.prices])

  const minPrice = Math.min(...chartData.map((p: PricePoint) => p.price)) * 0.98
  const maxPrice = Math.max(...chartData.map((p: PricePoint) => p.price)) * 1.02

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      {/* Chart header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm text-gray-500">Price history</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {data.prices[0]?.date} → {data.prices[data.prices.length - 1]?.date}
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold text-gray-900">
            {formatPrice(data.end_price)}
          </p>
          <p className={`text-xs font-medium ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
            {isPositive ? '+' : ''}{data.period_return_pct.toFixed(2)}%
          </p>
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart
          data={chartData}
          margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
        >
          <defs>
            <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={colour} stopOpacity={0.15} />
              <stop offset="95%" stopColor={colour} stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />

          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />

          <YAxis
            domain={[minPrice, maxPrice]}
            tickFormatter={v => `$${v.toFixed(0)}`}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            tickLine={false}
            axisLine={false}
            width={55}
          />

          <Tooltip content={<CustomTooltip />} />

          <Area
            type="monotone"
            dataKey="price"
            stroke={colour}
            strokeWidth={2}
            fill={`url(#${fillId})`}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>

      {/* Footer */}
      {data.is_stale && (
        <p className="text-xs text-amber-500 mt-2">
          ⚠ Data may be outdated{data.data_age_hours != null ? ` (${data.data_age_hours.toFixed(1)}h old)` : ''}
        </p>
      )}
    </div>
  )
}
