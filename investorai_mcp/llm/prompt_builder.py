"""
Prompt Builder for InvestorAI

Converts raw DB price rows into PriceSummaryStats. 
Then builds the LLM prompt. Raw OHLCV rows never 
enter the LLM context - only pre-computed statistics. 
"""

import statistics 
from dataclasses import dataclass
from datetime import date 
from typing import Optional 

from investorai_mcp.db.models import NewsArticle, PriceHistory

### ---- Closed-context system prompt -----------------------
#DO NOT CHANGE without re-running the full eval suite at 98% pass rate.

SYSTEM_PROMPT = """ You are a stock research assistant for casual retail investors.

RULES (follow strictly):
1. Only state financial figures that appear verbatim in the DATA PROVIDED below.
    Never use your training knowledge for any specific price, percentage, date,
    or finance metric. If a figure is not data provided, do not state it.
2. When you cite a number, append a citation rag: [source: DB • {date}]
3. For news-based claimbs, cite: [source: Publisher • URL]
4. If you cannot answer from the provided data, respond exactly:
    "I Don't have a reliable data to answer this"
5. Never give financial advice. Never recommend buying or selling.
6. Write for a casual investor. Avoid jargon. Explain acronyms on first use.
7. Keep responses to 3-5 sentences for summaries, or answer the question directly.
"""

# Chain-of-thought prompt for analytical questions over a specific date range.
# Used when the user asks about movement between two explicit dates.
COT_SYSTEM_PROMPT = """You are a stock research assistant for casual retail investors.

STRICT RULES:
1. Only cite financial figures that appear verbatim in DATA_PROVIDED.
   Never use training knowledge for any price, percentage, date, or metric.
2. Append [source: DB • YYYY-MM-DD] to every number you cite.
3. For news-based claims, cite: [source: Publisher • URL]
4. If you cannot answer from the provided data, say exactly:
   "I don't have reliable data to answer this accurately."
5. No financial advice. No buy/sell recommendations.
6. Write plainly for a casual investor.

REASONING STEPS (work through these before writing your final answer):
  Step 1 — PERIOD:  Identify the exact start and end dates shown in the data.
  Step 2 — PRICES:  Note the start price and end price for that window.
  Step 3 — CHANGE:  Compute the % return (end - start) / start × 100.
  Step 4 — CONTEXT: Note the period high, low, and any notable swings.
  Step 5 — ANSWER:  Write 2-4 plain sentences with citations for every figure.

Output ONLY Step 5. Do not show the intermediate steps.
"""


# ---- PriceSummaryStats------------------------

@dataclass
class PriceSummaryStats:
    """
    Pre-computed statictics from price history news. 
    This is what gets passsed to the LLM - never raw rows.
    """
    ticker_symbol: str
    range: str
    start_date: str
    end_date: str
    start_price: float
    end_price: float
    period_return_pct: float
    high_price: float
    high_date: str
    low_price: float
    low_date: str
    avg_price: float
    avg_daily_volume: float
    volatility_pct: float
    trading_days: int
    
    
    def to_text(self) -> str:
        """
        Format stats as plain text for the LLM prompt. 
        Keeps the data back under ~200 tokens.
        """
        direction = "up" if self.period_return_pct >= 0 else "down"
        return (
            f"STOCK DATA FOR {self.ticker_symbol} "
            f"({self.start_date} to {self.end_date}):\n"
            f"- Start price: ${self.start_price:.2f}\n"
            f"- End price:    ${self.end_price:.2f}\n"
            f"- Period return: {direction} {abs(self.period_return_pct):.2f}%\n"
            f"- 52-week high: ${self.high_price:.2f} on {self.high_date}\n"
            f"- 52-week low:  ${self.low_price:.2f} on {self.low_date}\n"
            f"- Average price: ${self.avg_price:.2f}\n"
            f"- Avg daily volume: {self.avg_daily_volume:,}\n"
            f"- Annualised volatility: {self.volatility_pct:.1f}%\n"
            f"- Trading days in period: {self.trading_days}\n"
        )

#-------Stats computation ----------------------------------

def compute_stats(
    symbol: str,
    period: str,
    rows: list[PriceHistory],
) -> Optional[PriceSummaryStats]:
    """
    Compute PriceSummaryStats from a list of PriceHistory rows. 
    Returns None if rows is empty
    """
    if not rows:
        return None
    
    adj_closes = [row.adj_close for row in rows]
    volumes = [row.volume for row in rows]
    
    start_price = adj_closes[0]
    end_price = adj_closes[-1]
    
    period_return_pct = (
        round((end_price - start_price) / start_price * 100, 2)
        if start_price > 0 else 0
    )
    
    high_price = max(adj_closes)
    low_price = min(adj_closes)
    high_date = rows[adj_closes.index(high_price)].date
    low_date = rows[adj_closes.index(low_price)].date
    
    avg_price = round(statistics.mean(adj_closes), 2)
    avg_volume = round(statistics.mean(volumes))
    
    #annualised volatality - std dev of daily returns × √252
    volatility_pct = 0.0
    if len(adj_closes) >= 2:
        daily_returns = [
            (adj_closes[i] - adj_closes[i - 1]) / adj_closes[i - 1]
            for i in range(1, len(adj_closes))
        ]
        if len(daily_returns) >= 2:
            volatility_pct = round(
                statistics.stdev(daily_returns) * (252 ** 0.5) * 100, 2
            )
    
    return PriceSummaryStats(
        ticker_symbol=symbol,
        range=period,
        start_date=str(rows[0].date),
        end_date=str(rows[-1].date),
        start_price=round(start_price, 2),
        end_price=round(end_price, 2),
        period_return_pct=period_return_pct,
        high_price=round(high_price, 2),
        high_date=str(high_date),
        low_price=round(low_price, 2),
        low_date=str(low_date),
        avg_price=avg_price,
        avg_daily_volume=avg_volume,
        volatility_pct=volatility_pct,
        trading_days=len(rows),
    )
    
### ---- Prompt Builder ----------------------------------

def build_prompt(
    stats: PriceSummaryStats,
    question: str,
    news: list[NewsArticle] | None = None,
    history: list[str] | None = None,
    use_cot: bool = False,
    news_focus: bool = False,
) -> list[dict]:
    """
    Build the full message list for LLM call
    
    Structure:
        1. System Prompt (closed-context rules)
        2. Earlier conversation summary (if history provided)
        3. Stock data block (PriceSummaryStats as text)
        4. News articles (if provided)
        5. User question
    
    Args:
        Stats: Pre-computed price statistics. 
        question: The user's question. 
        news: Optional list of recent news articles. 
        history: Optional compressed conversation history. 
        
    Returns: 
        List of message dicts ready for call_llm()
    """
    messages = [{"role": "system", "content": COT_SYSTEM_PROMPT if use_cot else SYSTEM_PROMPT}]
    
    # add compressed history if provided. 
    # (history already compressed by ChatHistoryManager)
    if history:
        messages.extend(history)
        
    # build the data block - this is what the LLM reasons from 
    data_block = stats.to_text()
    
    # Add news headlines if provided (max 5 to keep tokens low)
    news_block = ""
    if news:
        headlines = [
            f"- {article.headline} ({article.source} • {article.url})"
            for article in news[:5]
        ]
        if headlines:
            news_block = "RECENT NEWS:\n" + "\n".join(headlines) + "\n"

    # News-focused questions: lead with news, append price data as context only
    if news_focus and news_block:
        user_content = (
            f"{news_block}"
            f"\nPRICE CONTEXT (for reference only):\n{data_block}"
            f"\nUser question:\n{question}"
            f"\nInstruction: Answer based on the news articles above. "
            f"Only reference price data if directly relevant to the question."
        )
    else:
        user_content = (
            f"DATA_PROVIDED:\n{data_block}"
            f"\n{news_block}"
            f"\nUser question:\n{question}"
        )
    
    messages.append({"role": "user", "content": user_content})
    return messages
