import { ExternalLink } from 'lucide-react'
import type { NewsArticle } from '../types'

interface Props {
  articles: NewsArticle[]
  symbol: string
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 1)  return 'just now'
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7)   return `${days}d ago`
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function NewsFeed({ articles, symbol }: Props) {
  if (!articles.length) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">Latest News — {symbol}</h3>
        <p className="text-sm text-gray-400">No news articles found.</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Latest News — {symbol}</h3>
      <div className="space-y-3">
        {articles.map((article, i) => (
          <a
            key={i}
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start gap-3 p-3 rounded-lg hover:bg-gray-50 transition-colors group border border-transparent hover:border-gray-100"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 group-hover:text-blue-600 transition-colors line-clamp-2">
                {article.headline}
              </p>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-gray-400">{article.source}</span>
                <span className="text-xs text-gray-300">·</span>
                <span className="text-xs text-gray-400">{timeAgo(article.published_at)}</span>
                {article.sentiment_score !== null && (
                  <>
                    <span className="text-xs text-gray-300">·</span>
                    <span className={`text-xs font-medium ${
                      article.sentiment_score > 0 ? 'text-green-500'
                    : article.sentiment_score < 0 ? 'text-red-500'
                    : 'text-gray-400'
                    }`}>
                      {article.sentiment_score > 0 ? '▲ positive'
                     : article.sentiment_score < 0 ? '▼ negative'
                     : '● neutral'}
                    </span>
                  </>
                )}
              </div>
              {article.ai_summary && (
                <p className="text-xs text-gray-500 mt-1 line-clamp-2">{article.ai_summary}</p>
              )}
            </div>
            <ExternalLink size={14} className="text-gray-300 group-hover:text-blue-400 flex-shrink-0 mt-0.5" />
          </a>
        ))}
      </div>
    </div>
  )
}
