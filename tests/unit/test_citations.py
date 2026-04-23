"""Tests for citation extraction and source grounding"""

from investorai_mcp.llm.citations import (
    DBCitation,
    NewsCitation,
    extract_citations,
    format_citations_as_links,
    verify_citations_present,
)


# ---- Extract citations------------------------
def test_extracts_db_citation():
    text = "AAPL closed at $174.32  [source: DB • 2026-03-28]"
    result = extract_citations(text)
    assert len(result.db_citations) == 1
    assert result.db_citations[0].date == "2026-03-28"


def test_extracts_news_citation():
    text = "Apple announced a new product [source: Reuters • https://reuters.com/apple-product]"
    result = extract_citations(text)
    assert len(result.news_citations) == 1
    assert result.news_citations[0].publisher == "Reuters"
    assert result.news_citations[0].url == "https://reuters.com/apple-product"


def test_extracts_multiple_db_citations():
    text = (
        "Started at $150.00  [source: DB • 2026-04-01] Ended at $174.32  [source: DB • 2026-03-28]"
    )
    result = extract_citations(text)
    assert len(result.db_citations) == 2
    dates = [c.date for c in result.db_citations]
    assert "2026-04-01" in dates
    assert "2026-03-28" in dates


def test_extracts_mixed_citations():
    text = (
        "Price was $174.32 [source: DB • 2026-03-28]. "
        "Apple announced layoffs [source: Bloomberg • https://bloomberg.com/apple]"
    )
    result = extract_citations(text)
    assert len(result.db_citations) == 1
    assert len(result.news_citations) == 1


def test_no_citations_returns_empty():
    text = "AAPL had a great year with strong returns."
    result = extract_citations(text)
    assert len(result.db_citations) == 0
    assert len(result.news_citations) == 0
    assert result.has_citations is False


def test_has_citations_true_when_found():
    text = "AAPL closed at $174.32  [source: DB • 2026-03-28]"
    result = extract_citations(text)
    assert result.has_citations is True


def test_clean_text_removes_db_tag():
    text = "AAPL closed at $174.32  [source: DB • 2026-03-28]"
    result = extract_citations(text)
    assert "[source:" not in result.clean_text
    assert "174.32" in result.clean_text


def test_clean_text_removes_news_tag():
    text = "Apple announced a new product [source: Reuters • https://reuters.com/apple-product]"
    result = extract_citations(text)
    assert "[source:" not in result.clean_text
    assert "Apple announced" in result.clean_text


def test_empty_text_returns_empty():
    result = extract_citations("")
    assert result.db_citations == []
    assert result.news_citations == []
    assert result.clean_text == ""


def test_citation_type_db():
    c = DBCitation(date="2026-03-28")
    assert c.citation_type == "db"


def test_citation_type_news():
    c = NewsCitation(publisher="Reuters", url="https://reuters.com/apple")
    assert c.citation_type == "news"


###--- Format citations as links ----------------------------------


def test_format_db_citation_as_link():
    text = "Price $174.32 [source: DB • 2026-03-28]"
    result = extract_citations(text)
    links = format_citations_as_links(result)

    assert len(links) == 1
    assert links[0]["type"] == "db"
    assert links[0]["url"] is None
    assert "2026-03-28" in links[0]["label"]


def test_format_news_citation_as_link():
    text = "News [source: Reuters • https://reuters.com/article]"
    result = extract_citations(text)
    links = format_citations_as_links(result)

    assert len(links) == 1
    assert links[0]["type"] == "news"
    assert links[0]["url"] == "https://reuters.com/article"
    assert links[0]["label"] == "Reuters"


def test_format_empty_citations():
    result = extract_citations("AAPL had a great year.")
    links = format_citations_as_links(result)
    assert links == []


# --- Verify citations present ----------------------------------


def test_no_numbers_pass_without_citations():
    text = "AAPL had a great year with strong returns."
    assert verify_citations_present(text, has_numbers=True) is False


def test_numbers_with_citations_passes():
    text = "AAPL closed at $174.32  [source: DB • 2026-03-28]"
    assert verify_citations_present(text, has_numbers=True) is True


def test_empty_response_passes():
    assert verify_citations_present("", has_numbers=False) is True
