"""Pick the few pages of an annual report that matter for extraction.

A 280-page report is too long (and too expensive) to send to an LLM, and most
of it is irrelevant. We score every page with simple, explainable rules:

- income statement pages: the page title names the statement ("income
  statement", "profit or loss"), the page mentions revenue/total income and
  "attributable", and it is dense with numbers;
- balance sheet pages: the title names the statement ("balance sheet",
  "statement of financial position") and the page mentions liabilities;
- risk pages: many mentions of "risk" plus a risk-section heading
  ("principal risks", "risk management", "key risks", "risk factors").

Statements often run over two pages (assets on one, liabilities on the next),
so we keep the top two pages of each kind.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

_NUMBER = re.compile(r"\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\b\d+\.\d\b")

_INCOME_TITLE = re.compile(
    r"(consolidated\s+)?(income statement|statements? of (profit or loss|comprehensive income)|"
    r"profit (or|and) loss account)",
    re.IGNORECASE,
)
_BALANCE_TITLE = re.compile(
    r"(consolidated\s+)?(balance sheets?|statements? of financial position)", re.IGNORECASE
)
_RISK_HEADING = re.compile(
    r"(principal|key|material|top|significant) risks|risk (management|factors|review)|"
    r"enterprise risk|risk governance",
    re.IGNORECASE,
)
# A real statement title is followed by its period: "... for the financial year ended 31
# December 2025" or "... as at 31 March 2026". A bare mention ("included in the statement of
# comprehensive income") inside a footnote is not a title.
_PERIOD = r"\s+(for the (financial )?(year|period) ended|as at)\b"

_SUMMARY_TITLE = re.compile(
    r"(five|5|ten|10)[- ]year (financial )?summary|financial highlights", re.I
)


@dataclass(frozen=True)
class ReportPage:
    number: int  # 1-based PDF page index
    text: str


def load_pages(pdf_path: Path) -> list[ReportPage]:
    with pymupdf.open(pdf_path) as doc:
        return [ReportPage(i, page.get_text()) for i, page in enumerate(doc, start=1)]


def _head(text: str, chars: int = 400) -> str:
    return " ".join(text.split())[:chars]


def _title_zone(text: str) -> str:
    """Start and end of the page: titles sit in headers OR footers depending on the PDF."""
    flat = " ".join(text.split())
    return flat[:400] + " ... " + flat[-300:]


def _is_notes_page(text: str) -> bool:
    """Notes and the other primary statements mention the income statement / balance
    sheet in passing ("...included in the statement of comprehensive income") but are
    not the pages we want."""
    other = (
        r"notes to the (consolidated )?financial statements|changes in equity"
        r"|statements? of cash flows"
    )
    return bool(re.search(other, _title_zone(text), re.I))


def score_income(page: ReportPage) -> float:
    text = page.text
    numbers = len(_NUMBER.findall(text))
    if numbers < 15:
        return 0.0
    score = 0.0
    zone = _title_zone(text)
    if re.search(_INCOME_TITLE.pattern + _PERIOD, zone, re.I):
        score += 10  # a proper statement title with its period
    elif _INCOME_TITLE.search(zone):
        score += 4  # the words appear, but not as a title
    if _is_notes_page(text) and not re.search(_INCOME_TITLE.pattern + _PERIOD, zone, re.I):
        score -= 8  # notes discuss the statements but are not the statements
    if re.search(r"\b(revenue|total income|operating revenue)\b", text, re.I):
        score += 3
    if re.search(r"attributable to", text, re.I):
        score += 3
    if re.search(r"profit (for the (year|period)|before tax)|net profit", text, re.I):
        score += 2
    if _SUMMARY_TITLE.search(_title_zone(text)):
        score += 2  # five-year summaries repeat the headline numbers
    return score + min(numbers, 120) / 60


def score_balance(page: ReportPage) -> float:
    text = page.text
    numbers = len(_NUMBER.findall(text))
    if numbers < 15:
        return 0.0
    score = 0.0
    zone = _title_zone(text)
    if re.search(_BALANCE_TITLE.pattern + _PERIOD, zone, re.I):
        score += 10  # a proper statement title with its period
    elif _BALANCE_TITLE.search(zone):
        score += 4  # the words appear, but not as a title
    if _is_notes_page(text) and not re.search(_BALANCE_TITLE.pattern + _PERIOD, zone, re.I):
        score -= 8
    if re.search(r"\bliabilities\b", text, re.I):
        score += 3
    if re.search(r"borrowings|term loans|debt (issued|securities)|subordinated", text, re.I):
        score += 4
    if re.search(r"total equity|shareholders.? (funds|equity)", text, re.I):
        score += 1
    return score + min(numbers, 120) / 60


def score_risk(page: ReportPage) -> float:
    text = page.text
    mentions = len(re.findall(r"\brisks?\b", text, re.I))
    if mentions < 4:
        return 0.0
    score = min(mentions, 30) / 3
    if _RISK_HEADING.search(_head(text, 600)):
        score += 6
    if re.search(r"(mitigat|likelihood|impact|appetite)", text, re.I):
        score += 2
    # Financial-statement notes on "financial risk management" are numeric tables,
    # not the narrative risk disclosures we want: penalise number-heavy pages.
    score -= min(len(_NUMBER.findall(text)), 100) / 20
    return score


def _top(pages: list[ReportPage], scorer, n: int) -> list[int]:
    scored = sorted(((scorer(p), p.number) for p in pages), reverse=True)
    return [number for score, number in scored[:n] if score > 0]


def select_pages(
    pages: list[ReportPage], n_income: int = 2, n_balance: int = 2, n_risk: int = 4
) -> dict[str, list[int]]:
    """Return the page numbers chosen for each purpose."""
    return {
        "income": _top(pages, score_income, n_income),
        "balance": _top(pages, score_balance, n_balance),
        "risk": _top(pages, score_risk, n_risk),
    }
