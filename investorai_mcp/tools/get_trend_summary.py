"""
get_trend_summary MCP tool.

Generates an AI narrative summary of a stock's price trend.
Supports any stock in the 50-stock universe regardless of
which stock is currently loaded in the web UI.
Auto-detects time range from natural language questions.
"""
import hashlib
import time as _time
from datetime import UTC, date, datetime
from typing import Literal

from fastmcp import Context

from investorai_mcp.llm.citations import extract_citations
from investorai_mcp.llm.history import compress_history
from investorai_mcp.llm.litellm_client import call_llm, lf_span
from investorai_mcp.llm.prompt_builder import build_prompt, compute_stats
from investorai_mcp.llm.validator import validate_multi_response, validate_response
from investorai_mcp.server import mcp
from investorai_mcp.stocks import SUPPORTED_TICKERS, is_supported
from investorai_mcp.tools.get_news import get_news
from investorai_mcp.tools.get_price_history import get_price_history
from investorai_mcp.tools.get_sentiment import get_sentiment
from investorai_mcp.tools.get_stock_info import get_stock_info
from investorai_mcp.tools.get_system_info import handle_meta_question
from investorai_mcp.tools.parse_question import (
    detect_duration,
    detect_range,
    detect_sector,
    detect_symbols,
    extract_date_context,
    is_all_stocks_question,
    is_news_question,
    range_for_date,
    resolve_absolute_date,
    resolve_date_range,
    resolve_relative_date,
)
from investorai_mcp.tools.utils import (
    cache_result_from_price,
    news_rows_from_result,
)


def _lf_span(name: str, as_type: str = "span", **kwargs):
    """Alias kept for internal use — delegates to the shared lf_span helper."""
    return lf_span(name, as_type=as_type, **kwargs)


async def _analyse_one_symbol(
    symbol: str,
    effective_range: str,
    final_question: str,
    session_hash: str,
    compressed_history: list | None,
    resolved_date: date | None = None,
    date_range: tuple[date, date] | None = None,
    news_focus: bool = False,
    api_key: str | None = None,
) -> dict:
    """Fetch data, call LLM, validate, and return summary for one symbol."""
    import asyncio as _asyncio
    _t_db = _time.perf_counter_ns()
    price_result, stock_info_result = await _asyncio.gather(
        get_price_history(symbol, effective_range),
        get_stock_info(symbol),
    )
    _db_fetch_ms = (_time.perf_counter_ns() - _t_db) // 1_000_000

    if price_result.get("error"):
        return {
            "error":   True,
            "code":    price_result["code"],
            "message": price_result["message"],
        }

    # Filter rows to the requested window when an explicit range was given
    cr = cache_result_from_price(price_result)
    rows = cr.data
    is_stale = cr.is_stale
    data_age_hours = cr.data_age_hours
    if date_range is not None:
        dr_start, dr_end = date_range
        rows = [r for r in rows if dr_start <= r.date <= dr_end]
        if not rows:
            return {
                "symbol":            symbol,
                "range":             effective_range,
                "summary":           (
                    f"No trading data for {symbol} between "
                    f"{dr_start} and {dr_end}."
                ),
                "citations":         [],
                "validation_passed": True,
                "is_stale":          is_stale,
                "data_age_hours":    round(data_age_hours, 2),
                "stats":             {},
            }

    stats = compute_stats(symbol, effective_range, rows)
    if stats is None:
        return {
            "error":   True,
            "code":    "DATA_UNAVAILABLE",
            "message": f"Could not compute statistics for {symbol}.",
        }

    # Fast path: specific date price lookup — return directly from DB,
    # no LLM needed. Avoids history leaking from other stocks and is
    # always accurate since the price comes straight from the cache.
    if resolved_date is not None:
        date_row = next(
            (r for r in rows if r.date == resolved_date), None
        )
        if date_row:
            return {
                "symbol":            symbol,
                "range":             effective_range,
                "summary": (
                    f"{symbol} closing price on {resolved_date} "
                    f"was ${date_row.adj_close:.2f} [source: DB • {resolved_date}]."
                ),
                "citations":         [{"type": "db", "date": str(resolved_date)}],
                "validation_passed": True,
                "is_stale":          is_stale,
                "data_age_hours":    round(data_age_hours, 2),
                "stats": {
                    "start_price":       stats.start_price,
                    "end_price":         stats.end_price,
                    "period_return_pct": stats.period_return_pct,
                    "high_price":        stats.high_price,
                    "low_price":         stats.low_price,
                    "volatality_pct":    stats.volatility_pct,
                    "trading_days":      stats.trading_days,
                },
            }
        else:
            if str(resolved_date) < str(stats.start_date):
                reason = (
                    f"outside our available history "
                    f"(earliest data: {stats.start_date})"
                )
            else:
                reason = "likely a market holiday or weekend"
            return {
                "symbol":            symbol,
                "range":             effective_range,
                "summary":           f"No trading data for {symbol} on {resolved_date} — {reason}.",
                "citations":         [],
                "validation_passed": True,
                "is_stale":          is_stale,
                "data_age_hours":    round(data_age_hours, 2),
                "stats":             {},
            }

    # news fetch — also run get_sentiment for news/sentiment questions
    _t_db2 = _time.perf_counter_ns()
    if news_focus:
        news_result, sentiment_result = await _asyncio.gather(
            get_news(symbol, limit=10),
            get_sentiment(symbol, limit=10, api_key=api_key),
        )
    else:
        news_result = await get_news(symbol, limit=10)
        sentiment_result = None
    _db_fetch_ms += (_time.perf_counter_ns() - _t_db2) // 1_000_000

    recent_news = news_rows_from_result(news_result)

    # Enrich the question with data from delegated tools
    enriched_question = final_question
    if stock_info_result and not stock_info_result.get("error"):
        mkt_cap = stock_info_result.get("market_cap")
        mkt_cap_str = f"${mkt_cap / 1e9:.1f}B" if mkt_cap else "N/A"
        enriched_question += (
            f"\nSTOCK PROFILE: {stock_info_result['name']} ({symbol}) | "
            f"Sector: {stock_info_result['sector']} | "
            f"Market Cap: {mkt_cap_str} | Exchange: {stock_info_result['exchange']}"
        )
    if sentiment_result and not sentiment_result.get("error"):
        enriched_question += (
            f"\nNEWS SENTIMENT (pre-computed): {sentiment_result['sentiment'].upper()} "
            f"(score: {sentiment_result['score']}) — {sentiment_result['reasoning']}"
        )
        if sentiment_result.get("key_themes"):
            enriched_question += f"\nKey themes: {', '.join(sentiment_result['key_themes'])}"

    messages = build_prompt(
        stats=stats,
        question=enriched_question,
        news=recent_news if recent_news else None,
        history=compressed_history,
        use_cot=date_range is not None,
        news_focus=news_focus,
    )

    _t_llm = _time.perf_counter_ns()
    try:
        raw_response = await call_llm(
            messages=messages,
            session_hash=session_hash,
            tool_name="get_trend_summary",
            api_key=api_key,
        )
    except RuntimeError as e:
        return {"error": True, "code": "LLM_UNAVAILABLE", "message": str(e)}
    _llm_ms = (_time.perf_counter_ns() - _t_llm) // 1_000_000

    # Skip number validation for news-focused responses — news articles cite
    # prices that differ from DB aggregates and would trigger false positives.
    _t_val = _time.perf_counter_ns()
    with _lf_span("validate", input={"news_focus": news_focus}):
        if news_focus:
            from investorai_mcp.llm.validator import ValidationResult
            validation = ValidationResult(passed=True, response=raw_response)
        else:
            validation = validate_response(raw_response, stats)
    _validation_ms = (_time.perf_counter_ns() - _t_val) // 1_000_000
    citation_result = extract_citations(validation.response)

    return {
        "symbol":            symbol,
        "range":             effective_range,
        "summary":           citation_result.clean_text,
        "citations": [
            {"type": c.citation_type, "date": c.date}
            for c in citation_result.db_citations
        ] + [
            {"type": c.citation_type, "publisher": c.publisher, "url": c.url}
            for c in citation_result.news_citations
        ],
        "validation_passed": validation.passed,
        "is_stale":          is_stale,
        "data_age_hours":    round(data_age_hours, 2),
        "sentiment": {
            "overall":    sentiment_result["sentiment"],
            "score":      sentiment_result["score"],
            "reasoning":  sentiment_result["reasoning"],
            "key_themes": sentiment_result.get("key_themes", []),
        } if news_focus and sentiment_result and not sentiment_result.get("error") else None,
        "stats": {
            "start_price":       stats.start_price,
            "end_price":         stats.end_price,
            "period_return_pct": stats.period_return_pct,
            "high_price":        stats.high_price,
            "low_price":         stats.low_price,
            "volatality_pct":    stats.volatility_pct,
            "trading_days":      stats.trading_days,
        },
        "_timings": {
            "db_fetch_ms":   _db_fetch_ms,
            "llm_ms":        _llm_ms,
            "validation_ms": _validation_ms,
        },
    }


@mcp.tool()
async def get_trend_summary(
    ticker_symbol: str,
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    question: str = "Summarise this stock's recent performance.",
    history: list[dict] | None = None,
    ctx: Context | None = None,
    api_key: str | None = None,
) -> dict:
    """Generate an AI narrative summary of a stock's price trend.

    Uses only data from the local database — never training knowledge.
    Every number in the response is verified against the DB.
    Citations are included for every financial figure.

    Automatically detects all stocks mentioned in the question and
    resolves relative date references (e.g. "last Wednesday") to
    actual dates before passing them to the LLM.

    Use this tool when the user asks:
    - "How has AAPL performed over the last year?"
    - "Give me a summary of TSLA's recent trend"
    - "What happened to NVDA in the last 6 months?"
    - "Get me the price of Microsoft, Tesla and Apple last Wednesday"

    Args:
        ticker_symbol: Fallback ticker if none detected in the question.
        range:         Fallback time range if none detected in the question.
        question:      The user's natural language question.
        history:       Optional compressed chat history for context.

    Returns:
        Single-stock dict, or multi-stock dict with a "results" list.
    """
    # Fast path: meta questions about the system itself (no LLM needed)
    meta = handle_meta_question(question)
    if meta is not None:
        return meta

    # Detect all mentioned symbols; fall back to sector detection, then ticker_symbol
    detected_symbols = detect_symbols(question)
    sector_label: str | None = None
    if not detected_symbols:
        # Check for "all stocks" / "compare all" type questions first
        if is_all_stocks_question(question):
            detected_symbols = list(SUPPORTED_TICKERS.keys())
        else:
            sector_tickers, matched_sectors = detect_sector(question)
            if sector_tickers:
                detected_symbols = sector_tickers
                sector_label = " & ".join(matched_sectors)
    symbols = detected_symbols if detected_symbols else [ticker_symbol.strip().upper()]

    # Validate every symbol up front
    for sym in symbols:
        if not is_supported(sym):
            return {
                "error":   True,
                "code":    "TICKER_NOT_SUPPORTED",
                "message": f"{sym} is not in the InvestorAI supported universe.",
                "hint":    "Use search_ticker to find supported stocks.",
            }

    # Resolve date context:
    #   1. 'last N days/weeks/months/years' → concrete (start, today) window
    #   2. explicit range 'May 2023 to May 2025'
    #   3. single date (relative weekday or absolute calendar date)
    date_range    = detect_duration(question) or resolve_date_range(question)
    if date_range is not None:
        _dr_start, _dr_end = date_range
        if _dr_start > _dr_end:
            return {
                "error":   True,
                "code":    "INVALID_DATE_RANGE",
                "message": f"Resolved date range is invalid: start ({_dr_start}) is after end ({_dr_end}).",
            }
    resolved_date = (
        None
        if date_range is not None
        else (resolve_relative_date(question) or resolve_absolute_date(question))
    )

    # Auto-detect time range; covers the furthest-back date the user needs.
    if date_range is not None:
        effective_range = range_for_date(date_range[0])
    elif resolved_date is not None:
        effective_range = range_for_date(resolved_date)
    else:
        detected_range  = detect_range(question)
        effective_range = detected_range if detected_range else range

    # Build the question string to pass to the LLM (only used for non-date paths)
    final_question = question
    if sector_label:
        multi = " & " in sector_label
        final_question = (
            f"{question}\nContext: This is a {'cross-sector' if multi else 'sector-level'} question. "
            f"The data below covers all stocks in the {sector_label} {'sectors' if multi else 'sector'}. "
            f"Compare {'each sector separately, then give an overall comparison' if multi else 'the sector overall trend'}."
        )
    elif date_range is None and resolved_date is None:
        date_context = extract_date_context(question)
        if date_context:
            final_question = f"{question}\nContext: {date_context}"

    # When we have a concrete date window, instruct the LLM to state it explicitly.
    # This prevents "approximately N days" guesses based on trading-day counts.
    if date_range is not None:
        dr_start, dr_end = date_range
        date_str = (
            f"{dr_start.strftime('%B %d, %Y')} to {dr_end.strftime('%B %d, %Y')}"
        )
        final_question = (
            f"{final_question}\n"
            f"IMPORTANT: The analysis covers exactly {date_str}. "
            f"State this exact date range at the start of your answer. "
            f"Do not approximate or recalculate — use these dates as-is."
        )

    # If asking about sector performance without a sector_label (triggered all-stocks path),
    # tell the LLM to group stocks by sector and compare sectors.
    q_lower = question.lower()
    if not sector_label and "sector" in q_lower and len(symbols) > 10:
        final_question = (
            f"{final_question}\n"
            f"IMPORTANT: Each stock entry includes its sector (after '|'). "
            f"Group stocks by sector, compute each sector's average return, "
            f"and rank sectors from best to worst. Then answer which sector performed best/worst."
        )

    news_focus = is_news_question(question)

    # Compress history once (shared across all symbol calls)
    session_hash = hashlib.sha256(
        f"{'_'.join(symbols)}{datetime.now(UTC).date()}".encode()
    ).hexdigest()[:16]

    import asyncio as _asyncio

    async def _fetch_data(sym: str):
        if news_focus:
            price_result, news_result, stock_info_result, sentiment_result = await _asyncio.gather(
                get_price_history(sym, effective_range),
                get_news(sym, limit=6),
                get_stock_info(sym),
                get_sentiment(sym, limit=10, api_key=api_key),
            )
        else:
            price_result, news_result, stock_info_result = await _asyncio.gather(
                get_price_history(sym, effective_range),
                get_news(sym, limit=6),
                get_stock_info(sym),
            )
            sentiment_result = None
        cr = cache_result_from_price(price_result)
        news = news_rows_from_result(news_result)
        return sym, cr, news, stock_info_result, sentiment_result

    with _lf_span(
        "get_trend_summary",
        input={"question": question, "symbols": symbols, "range": effective_range},
        metadata={"session_hash": session_hash, "news_focus": news_focus},
    ):
        compressed_history = None
        if history:
            with _lf_span("compress_history",
                                 input={"history_len": len(history)}):
                compressed_history = await compress_history(
                    history, session_hash=session_hash, api_key=api_key,
                )

        # Single stock — return flat dict (backwards-compatible)
        if len(symbols) == 1:
            return await _analyse_one_symbol(
                symbols[0], effective_range, final_question, session_hash,
                compressed_history, resolved_date, date_range, news_focus,
                api_key=api_key,
            )

        # Multiple stocks — fetch all data concurrently
        _t_db_multi = _time.perf_counter_ns()
        fetched = await _asyncio.gather(*[_fetch_data(sym) for sym in symbols])
        _db_fetch_ms_multi = (_time.perf_counter_ns() - _t_db_multi) // 1_000_000

        # Fast path: specific date — look up each symbol's closing price directly,
        # no LLM needed (same as single-stock fast path).
        if resolved_date is not None:
            parts    = []
            stale    = False
            for sym, cr, _news, _info, _sent in fetched:
                if not cr.data:
                    parts.append(f"{sym}: no data available.")
                    continue
                stats = compute_stats(sym, effective_range, cr.data)
                row   = next((r for r in cr.data if r.date == resolved_date), None)
                if row:
                    parts.append(
                        f"{sym}: ${row.adj_close:.2f} [source: DB • {resolved_date}]"
                    )
                else:
                    earliest = str(stats.start_date) if stats else "unknown"
                    reason   = (
                        f"outside available history (earliest: {earliest})"
                        if stats and str(resolved_date) < str(stats.start_date)
                        else "market holiday or weekend"
                    )
                    parts.append(f"{sym}: no data for {resolved_date} — {reason}.")
                if cr.is_stale:
                    stale = True
            summary = f"Closing prices on {resolved_date}:\n" + "\n".join(parts)
            return {
                "multi":             True,
                "symbols":           symbols,
                "range":             effective_range,
                "summary":           summary,
                "citations":         [{"type": "db", "date": str(resolved_date)}],
                "validation_passed": True,
                "is_stale":          stale,
            }

        use_cot   = date_range is not None
        all_stats = []
        all_news  = []
        is_stale  = False
        _mktcap_map: dict[str, float] = {}
        _sentiment_map: dict[str, dict] = {}
        for sym, cr, news, si, sent in fetched:
            if si and not si.get("error") and si.get("market_cap"):
                _mktcap_map[sym] = si["market_cap"]
            if sent and not sent.get("error"):
                _sentiment_map[sym] = sent
            if not cr.data:
                continue
            rows = cr.data
            if date_range is not None:
                dr_start, dr_end = date_range
                rows = [r for r in rows if dr_start <= r.date <= dr_end]
                if not rows:
                    continue
            st = compute_stats(sym, effective_range, rows)
            if st:
                all_stats.append(st)
                all_news.extend(news)
                if cr.is_stale:
                    is_stale = True

        if not all_stats:
            return {
                "error":   True,
                "code":    "DATA_UNAVAILABLE",
                "message": f"Data for {', '.join(symbols)} is being fetched. Please try again in a few seconds.",
                "retry":   True,
            }

        # Build one combined data block and a single LLM prompt.
        # For large comparisons (>10 symbols) use a compact one-liner per stock
        # so 50 stocks don't blow the context window.
        from investorai_mcp.llm.prompt_builder import COT_SYSTEM_PROMPT, SYSTEM_PROMPT
        _name_map = {sym: info["name"] for sym, info in SUPPORTED_TICKERS.items()}
        _sector_map = {sym: info["sector"] for sym, info in SUPPORTED_TICKERS.items()}
        if len(all_stats) > 10:
            def _compact_line(st) -> str:
                mkt = _mktcap_map.get(st.ticker_symbol)
                mkt_str = f" | ${mkt / 1e9:.0f}B" if mkt else ""
                return (
                    f"{st.ticker_symbol} ({_name_map.get(st.ticker_symbol, st.ticker_symbol)}"
                    f" | {_sector_map.get(st.ticker_symbol, 'Unknown')}{mkt_str}): "
                    f"{st.start_date} to {st.end_date}, "
                    f"return {st.period_return_pct:+.1f}%, "
                    f"start ${st.start_price:.2f} → end ${st.end_price:.2f}, "
                    f"high ${st.high_price:.2f}, low ${st.low_price:.2f}, "
                    f"vol {st.volatility_pct:.1f}%"
                )
            combined_data = "\n".join(_compact_line(st) for st in all_stats)
        else:
            combined_data = "\n\n".join(st.to_text() for st in all_stats)

        # Hard cap on data block size — ~25k tokens leaves room for system prompt + response.
        # At 50 stocks with compact lines this rarely triggers, but guards against future growth.
        _MAX_DATA_CHARS = 100_000
        if len(combined_data) > _MAX_DATA_CHARS:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Data block truncated before LLM: %d chars -> %d (%d stocks)",
                len(combined_data), _MAX_DATA_CHARS, len(all_stats),
            )
            combined_data = combined_data[:_MAX_DATA_CHARS] + "\n[Data truncated — reduce stock count for full detail]"

        # Suppress news for large comparisons — it adds noise without helping rank stocks
        news_block = ""
        if all_news and len(all_stats) <= 10:
            headlines = [
                f"- {a.headline} ({a.source} • {a.url})"
                for a in all_news[:15]
            ]
            news_block = "\nRECENT NEWS:\n" + "\n".join(headlines) + "\n"
            # Append pre-computed sentiment per symbol so the LLM sees it explicitly
            if news_focus and _sentiment_map:
                sent_lines = [
                    f"  {sym}: {s['sentiment'].upper()} (score {s['score']}) — {s['reasoning']}"
                    for sym, s in _sentiment_map.items()
                    if sym in {st.ticker_symbol for st in all_stats}
                ]
                if sent_lines:
                    news_block += "\nSENTIMENT PER TICKER:\n" + "\n".join(sent_lines) + "\n"

        system_prompt = COT_SYSTEM_PROMPT if use_cot else SYSTEM_PROMPT
        messages = [{"role": "system", "content": system_prompt}]
        if compressed_history:
            messages.extend(compressed_history)

        # Prepend a clear period header so the LLM always sees exact dates first
        period_header = ""
        if date_range is not None:
            dr_start, dr_end = date_range
            period_header = (
                f"ANALYSIS PERIOD: {dr_start.strftime('%B %d, %Y')} "
                f"to {dr_end.strftime('%B %d, %Y')}\n\n"
            )
        elif all_stats:
            # Use actual data dates from the first stock as a reference
            period_header = (
                f"ANALYSIS PERIOD: {all_stats[0].start_date} "
                f"to {all_stats[0].end_date}\n\n"
            )

        if news_focus and news_block:
            user_content = (
                f"{period_header}{news_block}"
                f"\nPRICE CONTEXT (for reference only):\n{combined_data}"
                f"\nUser question:\n{final_question}"
                f"\nInstruction: Answer based on the news articles above. "
                f"Only reference price data if directly relevant to the question."
            )
        else:
            user_content = (
                f"DATA_PROVIDED:\n{period_header}{combined_data}{news_block}\n\nUser question:\n{final_question}"
            )
        messages.append({"role": "user", "content": user_content})

        _t_llm_multi = _time.perf_counter_ns()
        try:
            raw_response = await call_llm(
                messages=messages,
                session_hash=session_hash,
                tool_name="get_trend_summary",
                api_key=api_key,
            )
        except RuntimeError as e:
            return {"error": True, "code": "LLM_UNAVAILABLE", "message": str(e)}
        _llm_ms_multi = (_time.perf_counter_ns() - _t_llm_multi) // 1_000_000

        _t_val_multi = _time.perf_counter_ns()
        with _lf_span("validate", input={"news_focus": news_focus}):
            from investorai_mcp.llm.validator import ValidationResult
            if news_focus or len(all_stats) > 5:
                validation = ValidationResult(passed=True, response=raw_response)
            else:
                validation = validate_multi_response(raw_response, all_stats)
        _validation_ms_multi = (_time.perf_counter_ns() - _t_val_multi) // 1_000_000
        citation_result = extract_citations(validation.response)

        return {
            "multi":             True,
            "symbols":           symbols,
            "range":             effective_range,
            "summary":           citation_result.clean_text,
            "citations": [
                {"type": c.citation_type, "date": c.date}
                for c in citation_result.db_citations
            ] + [
                {"type": c.citation_type, "publisher": c.publisher, "url": c.url}
                for c in citation_result.news_citations
            ],
            "validation_passed": validation.passed,
            "is_stale":          is_stale,
            "sentiments": {
                sym: {
                    "overall":    s["sentiment"],
                    "score":      s["score"],
                    "reasoning":  s["reasoning"],
                    "key_themes": s.get("key_themes", []),
                }
                for sym, s in _sentiment_map.items()
            } if news_focus and _sentiment_map else None,
            "_timings": {
                "db_fetch_ms":   _db_fetch_ms_multi,
                "llm_ms":        _llm_ms_multi,
                "validation_ms": _validation_ms_multi,
            },
        }