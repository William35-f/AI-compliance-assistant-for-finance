"""One PDF page as readable paragraphs, with the cited paragraph flagged.

Powers the source panel in the UI: next to an answer, the reader sees the page
the citation points to, with the quoted paragraph highlighted and its own
paragraph number ("4.1.1", "3.6.", "(g)") in the margin.

The page is rebuilt from the same parser output that ingestion chunks, so a
quote that was verified against a chunk is found here too.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from regulens.pdf_parser import Paragraph, parse_pdf

# Leading paragraph labels used in MAS documents: "4.1.1", "3.6.", "12.", "(g)", "(iv)".
_LABEL = re.compile(r"^(\d+(?:\.\d+)+\.?|\d+\.|\([a-z]{1,4}\)|\([0-9]{1,2}\))\s+(?=\S)")
_WORD = re.compile(r"[a-z0-9]+")
# A paragraph counts as cited by word overlap only if it holds this share of the quote's words.
MIN_OVERLAP = 0.6


@dataclass(frozen=True)
class PageParagraph:
    label: str | None  # the document's own paragraph number, if it has one
    heading: str | None
    text: str
    cited: bool


@lru_cache(maxsize=8)
def _parsed(path: Path, mtime: float) -> tuple[tuple[Paragraph, ...], int]:
    """Parse once per file version; `mtime` in the key drops stale entries."""
    paragraphs, page_count = parse_pdf(path)
    return tuple(paragraphs), page_count


def load_document(path: Path) -> tuple[tuple[Paragraph, ...], int]:
    return _parsed(path, path.stat().st_mtime)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def split_label(text: str) -> tuple[str | None, str]:
    """'4.1.1 The FI should...' -> ('4.1.1', 'The FI should...')."""
    match = _LABEL.match(text)
    if not match:
        return None, text
    return match.group(1), text[match.end() :]


def cited_flags(texts: list[str], quote: str | None) -> list[bool]:
    """Which paragraphs hold the quote.

    1. Paragraphs that contain the whole quote.
    2. Otherwise a quote spanning paragraphs: every paragraph whose text sits inside it.
    3. Otherwise (a paraphrased quote): the paragraph sharing the most of the
       quote's words, if it shares at least MIN_OVERLAP of them.
    """
    if not quote or not quote.strip():
        return [False] * len(texts)
    q = _normalise(quote)
    norm = [_normalise(t) for t in texts]

    flags = [q in t for t in norm]
    if any(flags):
        return flags

    flags = [len(t) >= 30 and t in q for t in norm]
    if any(flags):
        return flags

    quote_words = set(_WORD.findall(q))
    if not quote_words:
        return [False] * len(texts)
    scores = [len(quote_words & set(_WORD.findall(t))) / len(quote_words) for t in norm]
    best = max(range(len(scores)), key=scores.__getitem__, default=None)
    return [i == best and scores[i] >= MIN_OVERLAP for i in range(len(texts))]


def page_paragraphs(
    paragraphs: tuple[Paragraph, ...], page: int, quote: str | None
) -> list[PageParagraph]:
    on_page = [p for p in paragraphs if p.page == page]
    flags = cited_flags([p.text for p in on_page], quote)
    out = []
    for p, cited in zip(on_page, flags, strict=True):
        label, body = split_label(p.text)
        # Some PDFs map dashes and bullets to U+FFFD; show a dash, not a replacement box.
        out.append(PageParagraph(label, p.heading, body.replace("�", "–"), cited))
    return out


def find_cited_page(
    paragraphs: tuple[Paragraph, ...], first: int, last: int, quote: str | None
) -> int:
    """First page in [first, last] where the quote is found; `first` if none."""
    if quote:
        for page in range(first, last + 1):
            if any(p.cited for p in page_paragraphs(paragraphs, page, quote)):
                return page
    return first
