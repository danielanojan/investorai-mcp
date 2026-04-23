import client from './client'

import type {
    Ticker, PriceHistory, DailySummary,
    NewsArticle, TrendSummary, TimeRange
} from '../types'

export const searchTickers = async (q: string): Promise<Ticker[]> => {
    const res = await client.get(`/tickers/search?q=${encodeURIComponent(q)}`)
    return res.data.matches
}

export const listTickers = async () : Promise<Ticker[]> => {
    const res = await client.get('/tickers')
    return res.data.tickers
}

export const getPriceHistory = async (
    symbol: string,
    range : TimeRange = '1Y'
) : Promise<PriceHistory> => {
    const res = await client.get(`/stocks/${symbol}/prices?range=${range}`)
    return res.data
}

export const getDailySummary = async (
    symbol: string,
    range : TimeRange = '1Y'
) : Promise<DailySummary> => {
    const res = await client.get(`/stocks/${symbol}/summary?range=${range}`)
    return res.data
}

export const getNews = async (
    symbol: string,
    limit = 10
) : Promise<NewsArticle[]> => {
    const res = await client.get(`/stocks/${symbol}/news?limit=${limit}`)
    return res.data.articles
}

export const getTrendSummary = async (
    symbol: string,
    question: string,
    range : TimeRange = '1Y',
) : Promise<TrendSummary> => {
    const res = await client.post(`/stocks/${symbol}/trend`, {
        question,
        range
    })
    return res.data
}

export const chat = async (
    symbol: string,
    question: string,
    history: {role: string; content: string}[] = []
) : Promise<{answer: string}> => {
    const res = await client.post(`/chat`, {
        symbol,
        question,
        history
    })
    return res.data
}
