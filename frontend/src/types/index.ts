export interface Ticker {
    symbol: string
    name: string
    sector: string
    exchange: string
}

export interface PricePoint {
    date: string, 
    price: number
    adj_close: number
    avg_price: number
    volume: number
}

export interface PriceHistory {
    symbol: string
    range: string
    history: PricePoint[]
    total_days: number
    start_price: string
    end_price: string
    high_price: string
    low_price: string
    period_return_pct: number
    is_stale: boolean
}

export interface DailySummary {
    symbol: string
    range: string
    start_price: number
    end_price: number
    period_return_pct: number
    high_price: number
    low_price: number
    avg_price: number
    volatality_pct: number
    trading_days: number
    is_stale: boolean
}

export interface Citation {
    type: "db" | "news"
    date? : string
    publisher? : string
    url? : string
}

export interface NewsArticle {
    headline: string
    source: string
    url: string
    published_at: string
    ai_summary: string | null
    sentiment_score: number | null
}

export interface TrendSummary {
    symbol: string
    range: string
    summary: string, 
    citations: Citation[]
    validation_passed: boolean
    stats : {
        start_price: number
        end_price: number
        period_return_pct: number
        high_price: number
        low_price: number
        volatality_pct: number
        trading_days: number
    }
}

export type TimeRange = '1W' | '1M' | '3M' | '6M' | '1Y' | '3Y' | '5Y'

