"""Tests for investorai_mcp/tools/utils.py"""

from datetime import date, datetime


def test_price_row_fields():
    from investorai_mcp.tools.utils import PriceRow

    row = PriceRow(
        date=date(2024, 1, 15), adj_close=150.0, close=151.0, avg_price=150.5, volume=1000000
    )
    assert row.date == date(2024, 1, 15)
    assert row.adj_close == 150.0
    assert row.close == 151.0
    assert row.avg_price == 150.5
    assert row.volume == 1000000


def test_news_row_defaults():
    from investorai_mcp.tools.utils import NewsRow

    row = NewsRow(
        headline="AAPL hits all-time high",
        source="Reuters",
        url="https://example.com",
        published_at=datetime(2024, 1, 15, 12, 0),
    )
    assert row.headline == "AAPL hits all-time high"
    assert row.ai_summary is None
    assert row.sentiment_score is None


def test_news_row_with_optional_fields():
    from investorai_mcp.tools.utils import NewsRow

    row = NewsRow(
        headline="Test",
        source="BBC",
        url="https://bbc.com",
        published_at=datetime(2024, 6, 1),
        ai_summary="Stock rose",
        sentiment_score=0.8,
    )
    assert row.ai_summary == "Stock rose"
    assert row.sentiment_score == 0.8


def test_price_cache_result_fields():
    from investorai_mcp.tools.utils import PriceCacheResult

    r = PriceCacheResult(data=[], is_stale=False, data_age_hours=2.5)
    assert r.data == []
    assert r.is_stale is False
    assert r.data_age_hours == 2.5


def test_price_rows_from_result_basic():
    from investorai_mcp.tools.utils import price_rows_from_result

    result = {
        "prices": [
            {
                "date": "2024-01-15",
                "adj_close": 150.0,
                "close": 151.0,
                "avg_price": 150.5,
                "volume": 500000,
            },
            {
                "date": "2024-01-16",
                "adj_close": 152.0,
                "close": 153.0,
                "avg_price": 152.5,
                "volume": 600000,
            },
        ]
    }
    rows = price_rows_from_result(result)
    assert len(rows) == 2
    assert rows[0].date == date(2024, 1, 15)
    assert rows[0].adj_close == 150.0
    assert rows[1].date == date(2024, 1, 16)


def test_price_rows_from_result_empty():
    from investorai_mcp.tools.utils import price_rows_from_result

    assert price_rows_from_result({}) == []
    assert price_rows_from_result({"prices": []}) == []


def test_cache_result_from_price_success():
    from investorai_mcp.tools.utils import cache_result_from_price

    result = {
        "prices": [
            {
                "date": "2024-01-15",
                "adj_close": 150.0,
                "close": 151.0,
                "avg_price": 150.5,
                "volume": 100,
            },
        ],
        "is_stale": False,
        "data_age_hours": 3.0,
    }
    cr = cache_result_from_price(result)
    assert cr.is_stale is False
    assert cr.data_age_hours == 3.0
    assert len(cr.data) == 1


def test_cache_result_from_price_error():
    from investorai_mcp.tools.utils import cache_result_from_price

    cr = cache_result_from_price({"error": True})
    assert cr.data == []
    assert cr.is_stale is True
    assert cr.data_age_hours == float("inf")


def test_news_rows_from_result_basic():
    from investorai_mcp.tools.utils import news_rows_from_result

    result = {
        "articles": [
            {
                "headline": "Test headline",
                "source": "Reuters",
                "url": "https://example.com",
                "published_at": "2024-01-15T12:00:00",
                "ai_summary": None,
                "sentiment_score": 0.5,
            }
        ]
    }
    rows = news_rows_from_result(result)
    assert len(rows) == 1
    assert rows[0].headline == "Test headline"
    assert rows[0].sentiment_score == 0.5


def test_news_rows_from_result_error():
    from investorai_mcp.tools.utils import news_rows_from_result

    assert news_rows_from_result({"error": True}) == []


def test_news_rows_from_result_empty():
    from investorai_mcp.tools.utils import news_rows_from_result

    assert news_rows_from_result({"articles": []}) == []
