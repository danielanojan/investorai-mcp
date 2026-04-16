import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, LineChart, Line,
} from 'recharts'
import {
  Activity, Database, Zap, CheckCircle,
  AlertTriangle, Clock, TrendingUp, RefreshCw,
} from 'lucide-react'
import client from '../api/client'

function StatCard({
  label, value, sub, icon: Icon, colour = 'blue', alert = false
}: {
  label:   string
  value:   string | number
  sub?:    string
  icon:    any
  colour?: string
  alert?:  boolean
}) {
  const colours: Record<string, string> = {
    blue:   'bg-blue-50 text-blue-600',
    green:  'bg-green-50 text-green-600',
    amber:  'bg-amber-50 text-amber-600',
    red:    'bg-red-50 text-red-600',
    purple: 'bg-purple-50 text-purple-600',
  }
  return (
    <div className={`bg-white rounded-xl border p-4 ${
      alert ? 'border-amber-200' : 'border-gray-200'
    } shadow-sm`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">
          {label}
        </span>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${colours[colour]}`}>
          <Icon size={15} />
        </div>
      </div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h3 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">
        {title}
      </h3>
      {children}
    </div>
  )
}

export default function MonitoringDashboard() {
  const [tab, setTab] = useState<'overview' | 'langfuse' | 'latency' | 'data'>('overview')

  const { data: dbStats, isLoading: dbLoading, refetch: refetchDb } = useQuery({
    queryKey:        ['monitoring-db'],
    queryFn:         () => client.get('/monitoring/db').then(r => r.data),
    refetchInterval: 30_000,
  })

  const { data: lfStats, isLoading: lfLoading } = useQuery({
    queryKey:        ['monitoring-langfuse'],
    queryFn:         () => client.get('/monitoring/langfuse')
                             .then(r => r.data)
                             .catch((e: any) => e.response?.data ?? { error: { code: 'FETCH_ERROR', message: String(e) } }),
    refetchInterval: 60_000,
    retry:           0,
  })

  const { data: latStats, isLoading: latLoading } = useQuery({
    queryKey:        ['monitoring-latency'],
    queryFn:         () => client.get('/monitoring/latency').then(r => r.data),
    refetchInterval: 30_000,
  })

  const passRate   = dbStats?.quality?.pass_rate
  const totalToday = dbStats?.llm_today?.total_queries ?? 0

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">
              InvestorAI Playground
            </h1>
            <p className="text-xs text-gray-500">
              LLM monitoring · data health · eval quality
            </p>
          </div>
          <button
            onClick={() => refetchDb()}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-200"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6">

        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          {(['overview', 'latency', 'langfuse', 'data'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm rounded-lg font-medium transition-colors capitalize ${
                tab === t
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'
              }`}
            >
              {t === 'langfuse' ? 'Langfuse Traces' : t === 'latency' ? 'Latency' : t}
            </button>
          ))}
        </div>

        {dbLoading && (
          <div className="text-center py-20 text-gray-400 text-sm">
            Loading monitoring data...
          </div>
        )}

        {/* ── Overview tab ──────────────────────────────────────── */}
        {tab === 'overview' && dbStats && (
          <>
            <Section title="Today">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                  label="Queries today"
                  value={totalToday}
                  icon={Activity}
                  colour="blue"
                />
                <StatCard
                  label="Avg latency"
                  value={`${dbStats.llm_today.avg_latency_ms}ms`}
                  icon={Clock}
                  colour="purple"
                />
                <StatCard
                  label="Avg tokens in"
                  value={dbStats.llm_today.avg_tokens_in}
                  sub="prompt tokens"
                  icon={TrendingUp}
                  colour="blue"
                />
                <StatCard
                  label="Avg tokens out"
                  value={dbStats.llm_today.avg_tokens_out}
                  sub="completion tokens"
                  icon={TrendingUp}
                  colour="green"
                />
              </div>
            </Section>

            <Section title="Last 7 Days">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                <StatCard
                  label="Total queries"
                  value={dbStats.llm_week.total_queries}
                  icon={Activity}
                  colour="blue"
                />
                <StatCard
                  label="Tokens in (total)"
                  value={dbStats.llm_week.tokens_in.toLocaleString()}
                  icon={TrendingUp}
                  colour="blue"
                />
                <StatCard
                  label="Tokens out (total)"
                  value={dbStats.llm_week.tokens_out.toLocaleString()}
                  icon={TrendingUp}
                  colour="green"
                />
                <StatCard
                  label="Eval pass rate"
                  value={passRate !== null && passRate !== undefined
                    ? `${passRate}%` : 'No evals'}
                  icon={CheckCircle}
                  colour={passRate >= 98 ? 'green' : passRate >= 90 ? 'amber' : 'red'}
                  alert={passRate !== null && passRate < 98}
                />
              </div>

              {/* Daily sparkline */}
              {dbStats.daily_counts?.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-4">
                  <p className="text-xs text-gray-500 font-medium mb-3">
                    Daily query volume
                  </p>
                  <ResponsiveContainer width="100%" height={120}>
                    <LineChart data={dbStats.daily_counts}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis
                        dataKey="day"
                        tick={{ fontSize: 10, fill: '#9ca3af' }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: '#9ca3af' }}
                        tickLine={false}
                        axisLine={false}
                        width={30}
                      />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="count"
                        stroke="#2563eb"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Section>

            {/* Provider + error breakdown */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {dbStats.providers?.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-4">
                  <p className="text-xs text-gray-500 font-medium mb-3">
                    Provider breakdown (7d)
                  </p>
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={dbStats.providers}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis
                        dataKey="provider"
                        tick={{ fontSize: 11, fill: '#9ca3af' }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: '#9ca3af' }}
                        tickLine={false}
                        axisLine={false}
                        width={30}
                      />
                      <Tooltip />
                      <Bar dataKey="count" fill="#2563eb" radius={[4,4,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {dbStats.errors?.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-4">
                  <p className="text-xs text-gray-500 font-medium mb-3">
                    Status breakdown (7d)
                  </p>
                  <div className="space-y-2">
                    {dbStats.errors.map((e: any) => (
                      <div key={e.status}
                           className="flex items-center justify-between py-1">
                        <span className={`text-sm font-medium ${
                          e.status === 'success' ? 'text-green-600'
                          : e.status === 'error'  ? 'text-red-600'
                          : 'text-amber-600'
                        }`}>
                          {e.status}
                        </span>
                        <span className="text-sm text-gray-500">{e.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        {/* ── Latency tab ────────────────────────────────────────── */}
        {tab === 'latency' && (
          <>
            {latLoading && (
              <div className="text-center py-20 text-gray-400 text-sm">
                Loading latency data...
              </div>
            )}
            {latStats && (
              <>
                {latStats.total_calls === 0 ? (
                  <div className="text-center py-20 text-gray-400 text-sm">
                    No chat calls recorded yet. Make some queries first.
                  </div>
                ) : (
                  <>
                    <Section title="End-to-end latency (all-time, successful calls)">
                      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                        <StatCard label="P50"  value={latStats.p50_ms != null ? `${latStats.p50_ms} ms` : '—'} icon={Clock}       colour="green"  />
                        <StatCard label="P95"  value={latStats.p95_ms != null ? `${latStats.p95_ms} ms` : '—'} icon={Clock}       colour="amber"  />
                        <StatCard label="P99"  value={latStats.p99_ms != null ? `${latStats.p99_ms} ms` : '—'} icon={Clock}       colour="red"    />
                        <StatCard label="Avg"  value={latStats.avg_ms  != null ? `${latStats.avg_ms} ms` : '—'} icon={TrendingUp} colour="blue"   />
                      </div>
                      <div className="mt-4 grid grid-cols-2 gap-4">
                        <StatCard label="Total calls"    value={latStats.total_calls}   icon={Activity} colour="blue"  />
                        <StatCard
                          label="Outliers > P95"
                          value={latStats.outlier_count}
                          sub={`${latStats.success_calls > 0 ? ((latStats.outlier_count / latStats.success_calls) * 100).toFixed(1) : 0}% of successful calls`}
                          icon={AlertTriangle}
                          colour={latStats.outlier_count > 0 ? 'amber' : 'green'}
                          alert={latStats.outlier_count > 0}
                        />
                      </div>
                    </Section>

                    {/* TTFT section */}
                    <Section title="Time to first token (TTFT)">
                      {latStats.ttft?.samples > 0 ? (
                        <>
                          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                            <StatCard
                              label="TTFT P50"
                              value={latStats.ttft.p50_ms != null ? `${latStats.ttft.p50_ms} ms` : '—'}
                              icon={Zap}
                              colour="green"
                            />
                            <StatCard
                              label="TTFT P95"
                              value={latStats.ttft.p95_ms != null ? `${latStats.ttft.p95_ms} ms` : '—'}
                              icon={Zap}
                              colour="amber"
                            />
                            <StatCard
                              label="TTFT P99"
                              value={latStats.ttft.p99_ms != null ? `${latStats.ttft.p99_ms} ms` : '—'}
                              icon={Zap}
                              colour="red"
                            />
                            <StatCard
                              label="TTFT Avg"
                              value={latStats.ttft.avg_ms != null ? `${latStats.ttft.avg_ms} ms` : '—'}
                              sub={`${latStats.ttft.samples} samples`}
                              icon={TrendingUp}
                              colour="blue"
                            />
                          </div>
                          <p className="text-xs text-gray-400 mt-3">
                            TTFT = time from request received to first token streamed.
                            In this architecture this equals server processing time (LLM call + data fetch).
                          </p>
                        </>
                      ) : (
                        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-sm text-gray-400">
                          No TTFT data yet — make some chat queries first.
                        </div>
                      )}
                    </Section>

                    {/* Component timing breakdown */}
                    <Section title="Component timing breakdown">
                      {latStats.components?.db_fetch?.samples > 0 ? (
                        <>
                          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                            <div className="overflow-x-auto">
                              <table className="w-full text-sm">
                                <thead>
                                  <tr className="text-left text-xs text-gray-400 uppercase tracking-wide border-b border-gray-100 bg-gray-50">
                                    <th className="px-4 py-3">Component</th>
                                    <th className="px-4 py-3 text-right">Avg</th>
                                    <th className="px-4 py-3 text-right">P50</th>
                                    <th className="px-4 py-3 text-right">P95</th>
                                    <th className="px-4 py-3 text-right">P99</th>
                                    <th className="px-4 py-3 text-right">Samples</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {[
                                    { key: 'db_fetch',   label: 'DB fetch + news',  colour: 'text-blue-600'   },
                                    { key: 'llm',        label: 'LLM call',         colour: 'text-purple-600' },
                                    { key: 'validation', label: 'Validation',        colour: 'text-green-600'  },
                                  ].map(({ key, label, colour }) => {
                                    const s = latStats.components?.[key]
                                    const fmt = (v: number | null) => v != null ? `${v} ms` : '—'
                                    return (
                                      <tr key={key} className="border-b border-gray-50 hover:bg-gray-50">
                                        <td className={`px-4 py-3 font-medium ${colour}`}>{label}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{fmt(s?.avg_ms)}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{fmt(s?.p50_ms)}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{fmt(s?.p95_ms)}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{fmt(s?.p99_ms)}</td>
                                        <td className="px-4 py-3 text-right text-gray-400 text-xs">{s?.samples ?? 0}</td>
                                      </tr>
                                    )
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                          <p className="text-xs text-gray-400 mt-3">
                            Timings are per-request averages summed across all symbols analysed.
                            Total latency &gt; db_fetch + llm + validation due to orchestration overhead.
                          </p>
                        </>
                      ) : (
                        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-sm text-gray-400">
                          No component timing data yet — make some chat queries first.
                        </div>
                      )}
                    </Section>

                    <Section title={`Slow queries exceeding P95 (${latStats.p95_ms} ms)`}>
                      {latStats.outliers.length === 0 ? (
                        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-sm text-green-700">
                          All calls are within P95. No slow queries to report.
                        </div>
                      ) : (
                        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                          <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                              <thead>
                                <tr className="text-left text-xs text-gray-400 uppercase tracking-wide border-b border-gray-100">
                                  <th className="px-4 py-3">Question</th>
                                  <th className="px-4 py-3">Symbols</th>
                                  <th className="px-4 py-3">Latency</th>
                                  <th className="px-4 py-3">TTFT</th>
                                  <th className="px-4 py-3">Excess</th>
                                  <th className="px-4 py-3">Time</th>
                                </tr>
                              </thead>
                              <tbody>
                                {latStats.outliers.map((o: any) => (
                                  <tr key={o.id} className="border-b border-gray-50 hover:bg-amber-50">
                                    <td className="px-4 py-3 text-gray-700 max-w-xs">
                                      <span title={o.question}>
                                        {o.question.length > 60
                                          ? o.question.slice(0, 60) + '…'
                                          : o.question}
                                      </span>
                                    </td>
                                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                                      {o.symbols}
                                    </td>
                                    <td className="px-4 py-3 font-semibold text-amber-600">
                                      {o.total_latency_ms} ms
                                    </td>
                                    <td className="px-4 py-3 text-gray-500 text-xs">
                                      {o.ttft_ms != null ? `${o.ttft_ms} ms` : '—'}
                                    </td>
                                    <td className="px-4 py-3 text-red-500 text-xs">
                                      +{o.excess_ms} ms
                                    </td>
                                    <td className="px-4 py-3 text-gray-400 text-xs">
                                      {new Date(o.ts).toLocaleString()}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </Section>
                  </>
                )}
              </>
            )}
          </>
        )}

        {/* ── Langfuse tab ───────────────────────────────────────── */}
        {tab === 'langfuse' && (
          <>
            {lfLoading && (
              <div className="text-center py-20 text-gray-400 text-sm">
                Fetching Langfuse traces...
              </div>
            )}

            {lfStats?.error && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-700">
                <strong>Langfuse not available:</strong>{' '}
                {lfStats.error.message}
              </div>
            )}

            {lfStats && !lfStats.error && (
              <>
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                  <StatCard
                    label="Total traces"
                    value={lfStats.total_traces}
                    icon={Activity}
                    colour="blue"
                  />
                  <StatCard
                    label="Avg latency"
                    value={`${lfStats.avg_latency_ms}ms`}
                    icon={Clock}
                    colour="purple"
                  />
                  <StatCard
                    label="Traces fetched"
                    value={lfStats.traces?.length ?? 0}
                    sub="most recent"
                    icon={Zap}
                    colour="green"
                  />
                </div>

                {/* Traces table */}
                <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <p className="text-sm font-medium text-gray-700">
                      Recent traces
                    </p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs text-gray-400 uppercase tracking-wide border-b border-gray-100">
                          <th className="px-4 py-3">Name</th>
                          <th className="px-4 py-3">Latency</th>
                          <th className="px-4 py-3">Status</th>
                          <th className="px-4 py-3">Time</th>
                          <th className="px-4 py-3"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {lfStats.traces?.map((trace: any, i: number) => (
                          <tr key={i}
                              className="border-b border-gray-50 hover:bg-gray-50">
                            <td className="px-4 py-3 font-medium text-gray-700">
                              {trace.name || trace.id?.slice(0, 8)}
                            </td>
                            <td className="px-4 py-3 text-gray-500">
                              {trace.latency ? `${Math.round(trace.latency)}ms` : '—'}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                                trace.level === 'ERROR'
                                  ? 'bg-red-50 text-red-600'
                                  : 'bg-green-50 text-green-600'
                              }`}>
                                {trace.level || 'OK'}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-gray-400 text-xs">
                              {trace.timestamp
                                ? new Date(trace.timestamp).toLocaleString()
                                : '—'}
                            </td>
                            <td className="px-4 py-3">
                              {lfStats.trace_url_base && trace.id && (
                                <a
                                  href={`${lfStats.trace_url_base}/${trace.id}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-xs text-blue-600 hover:text-blue-800 hover:underline whitespace-nowrap"
                                >
                                  View ↗
                                </a>
                              )}
                            </td>
                          </tr>
                        ))}
                        {(!lfStats.traces || lfStats.traces.length === 0) && (
                          <tr>
                            <td colSpan={4}
                                className="px-4 py-8 text-center text-gray-400 text-sm">
                              No traces found. Make some queries first.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </>
        )}

        {/* ── Data health tab ────────────────────────────────────── */}
        {tab === 'data' && dbStats && (
          <>
            <Section title="Price Data">
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                <StatCard
                  label="Total price rows"
                  value={dbStats.price_data.total_rows.toLocaleString()}
                  icon={Database}
                  colour="blue"
                />
                <StatCard
                  label="Tickers covered"
                  value={`${dbStats.price_data.tickers_covered} / 50`}
                  icon={CheckCircle}
                  colour="green"
                />
                <StatCard
                  label="Stale cache entries"
                  value={dbStats.price_data.stale_count}
                  icon={AlertTriangle}
                  colour={dbStats.price_data.stale_count > 5 ? 'amber' : 'green'}
                  alert={dbStats.price_data.stale_count > 5}
                />
              </div>

              {/* Rows per ticker chart */}
              {dbStats.price_data.rows_per_ticker?.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-4">
                  <p className="text-xs text-gray-500 font-medium mb-3">
                    Top 10 tickers by row count
                  </p>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={dbStats.price_data.rows_per_ticker}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis
                        dataKey="symbol"
                        tick={{ fontSize: 10, fill: '#9ca3af' }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: '#9ca3af' }}
                        tickLine={false}
                        axisLine={false}
                        width={40}
                      />
                      <Tooltip />
                      <Bar dataKey="count" fill="#0F6E56" radius={[4,4,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Section>
          </>
        )}

      </main>
    </div>
  )
}
