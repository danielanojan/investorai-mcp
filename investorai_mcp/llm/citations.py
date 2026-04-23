"""
Source grounding and citation extraction

Parses citation tags from LLM responses and converts them
into structured metadata. Verifies financial claim
has a source before the response reaches the user

Citation formats:
    Price data: [source: DB • 2026-03-28]
    News: [source: Reuters • https://reuters.com/...]

"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ----Citation patterns ----------------------------------

_DB_CITATION = re.compile(r"\[source:\s*DB\s*[•·]\s*(\d{4}-\d{2}-\d{2})\]")

# Matches: [source: Publisher • https://...]
_NEWS_CITATION = re.compile(r"\[source:\s*([^•\]]+?)\s*[•·]\s*(https?://[^\]]+)\]")


###--- Data classes ----------------------------------
@dataclass
class DBCitation:
    """A citation pointing to a specific date in the price database."""

    date: str
    citation_type: str = "db"


@dataclass
class NewsCitation:
    """A citation pointing to a news article."""

    publisher: str
    url: str
    citation_type: str = "news"


@dataclass
class CitationResult:
    """Result of citation extraction from a response."""

    db_citations: list[DBCitation]
    news_citations: list[NewsCitation]
    clean_text: str  # response with citaiton tags removed
    has_citations: bool  # True if atleast one citation found


# ---Extraction logic ----------------------------------
def extract_citations(text: str) -> CitationResult:
    """
    Extract all citaiton tags from response text

    Parses both DB citations and news citations.
    Returns structured metadata and cleaned text
    with citation tags removed.

    Args:
        text: Raw LLM response with [source: ...] tags

    Returns:
        CitationResult with extracted citations and cleaned text
    """
    db_citations = []
    news_citations = []

    # Extract DB citations
    for match in _DB_CITATION.finditer(text):
        db_citations.append(DBCitation(date=match.group(1)))

    # Extract news citations
    for match in _NEWS_CITATION.finditer(text):
        publisher = match.group(1).strip()
        url = match.group(2).strip()
        news_citations.append(NewsCitation(publisher=publisher, url=url))

    # Remove all citation tags from text and then display
    clean_text = _DB_CITATION.sub("", text)
    clean_text = _NEWS_CITATION.sub("", clean_text)
    clean_text = clean_text.strip()

    return CitationResult(
        db_citations=db_citations,
        news_citations=news_citations,
        clean_text=clean_text,
        has_citations=bool(db_citations or news_citations),
    )


def format_citations_as_links(result: CitationResult) -> list[dict]:
    """
    Convert citations to a list of link objects for the web UI

    Returns:
        List of dits with type, label and URL (where applicable)
    """
    links = []

    for citation in result.db_citations:
        links.append(
            {
                "type": "db",
                "label": f"DB • {citation.date}",
                "url": None,  # DB citations don't have a URL
            }
        )

    for citation in result.news_citations:
        links.append(
            {
                "type": "news",
                "label": citation.publisher,
                "url": citation.url,
            }
        )
    return links


def verify_citations_present(
    response_text: str,
    has_numbers: bool,
) -> bool:
    """
    Verify that a response containing numbers has at least one citation.

    Used as part of the validation pipeline - a response with
    financial numbers but no citation fails this check

    Args;
        response_text : The LLM response.
        has_numbers: Whether the response contains financial numbers.

    Returns:
        True if citations are present or no numbers in response.
        False if numbers present but no citations found.
    """
    if not has_numbers:
        return True

    result = extract_citations(response_text)
    if not result.has_citations:
        logger.warning("Response contains numbers but no citaitons")
        return False

    return True
