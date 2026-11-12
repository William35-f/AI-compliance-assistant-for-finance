"""Turn a PDF into a list of paragraphs, each tagged with its page and nearest heading.

How it works (PyMuPDF gives us every text line with its font size, boldness
and position):

1. Find the document's body font size: the size used by the most characters.
2. Remove running headers/footers: short lines in the top/bottom margin that
   repeat on many pages (e.g. "Monetary Authority of Singapore 12").
3. Classify each remaining line as a heading if it is short and either clearly
   bigger than body text or entirely bold.
4. Walk the lines in order. Consecutive heading lines are merged
   ("3.2" + "Policies, Standards and Procedures"). Body lines in the same
   PDF block are joined into one paragraph, tagged with the latest heading.

These are heuristics. They work well on the MAS guidelines, and reasonably on
glossy annual reports, where diagrams and tables produce some noise.
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

# Bump this when parsing logic changes, so ingest.py knows to re-process files.
PARSER_VERSION = "2"  # 2: drop superscript footnote markers

MARGIN_FRACTION = 0.10  # top/bottom 10% of a page counts as header/footer zone
REPEAT_FRACTION = 0.30  # a margin line on >=30% of pages is a running header/footer
TOC_MIN_LEADER_LINES = 5  # a page with >=5 dot-leader lines is a table of contents
MAX_HEADING_WORDS = 14
MAX_HEADING_CHARS = 120

_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
_SECTION_NUMBER = re.compile(r"^(\d+(\.\d+)*\.?|[A-Z]\.|[IVX]+\.?|Annex \w+|Part \w+)$")
_DANGLING_WORD = re.compile(
    r"\b(the|of|and|or|to|a|an|in|for|with|by|on|that|which|its|their|our|as)$", re.IGNORECASE
)
_DOT_LEADER = re.compile(r"(\.\s?){4,}|…{2,}")
_PAGE_NUMBER = re.compile(r"^(page\s*)?\d+(\s*(of|/)\s*\d+)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Paragraph:
    page: int  # 1-based PDF page index (what a PDF viewer shows)
    heading: str | None  # nearest heading above this paragraph
    text: str


@dataclass
class _Line:
    page: int
    block: int  # PyMuPDF block number within the page
    text: str
    size: float
    bold: bool
    in_margin: bool


def is_footnote_marker(span: dict) -> bool:
    """A superscript number glued to a word, e.g. the "19" in "notification19".

    Left in, it turns "notification" into the token "notification19", which
    full-text search can no longer match. PyMuPDF sets flag bit 1 on superscripts.
    """
    return bool(span["flags"] & 1) and bool(re.fullmatch(r"\s*\d{1,3}\s*", span["text"]))


def _extract_lines(doc: pymupdf.Document) -> list[_Line]:
    lines: list[_Line] = []
    for page_index, page in enumerate(doc):
        height = page.rect.height
        # sort=False keeps the PDF's own content order, which usually follows
        # columns correctly; sort=True would interleave multi-column layouts.
        page_dict = page.get_text("dict", sort=False)
        for block_no, block in enumerate(page_dict["blocks"]):
            for line in block.get("lines", []):
                kept_spans = [s for s in line["spans"] if not is_footnote_marker(s)]
                spans = [s for s in kept_spans if s["text"].strip()]
                if not spans:
                    continue
                text = " ".join("".join(s["text"] for s in kept_spans).split())
                # Use the font of the span that carries the most characters.
                main = max(spans, key=lambda s: len(s["text"]))
                bold = all(s["flags"] & 16 or _BOLD_FONT.search(s["font"]) for s in spans)
                y0, y1 = line["bbox"][1], line["bbox"][3]
                in_margin = y1 < height * MARGIN_FRACTION or y0 > height * (1 - MARGIN_FRACTION)
                lines.append(
                    _Line(page_index + 1, block_no, text, round(main["size"], 1), bold, in_margin)
                )
    return lines


def _body_size(lines: list[_Line]) -> float:
    """The font size used by the most characters is the body text size."""
    sizes: Counter[float] = Counter()
    for line in lines:
        sizes[line.size] += len(line.text)
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _normalise(text: str) -> str:
    """Make 'Page 3' and 'Page 14' look the same so repeats can be counted."""
    return re.sub(r"\d+", "#", text.lower()).strip()


def _remove_headers_footers(lines: list[_Line], page_count: int) -> list[_Line]:
    pages_with: dict[str, set[int]] = {}
    for line in lines:
        if line.in_margin:
            pages_with.setdefault(_normalise(line.text), set()).add(line.page)
    threshold = max(3, REPEAT_FRACTION * page_count)
    repeated = {norm for norm, pages in pages_with.items() if len(pages) >= threshold}

    kept = []
    for line in lines:
        if line.in_margin and (_normalise(line.text) in repeated or _PAGE_NUMBER.match(line.text)):
            continue
        kept.append(line)
    return kept


def _remove_toc_pages(lines: list[_Line]) -> list[_Line]:
    """Drop table-of-contents pages (many "Title ...... 12" lines).

    They contain every heading in the document but no content, so they would
    only produce confusing chunks.
    """
    leaders: Counter[int] = Counter(line.page for line in lines if _DOT_LEADER.search(line.text))
    toc_pages = {page for page, n in leaders.items() if n >= TOC_MIN_LEADER_LINES}
    return [line for line in lines if line.page not in toc_pages]


def is_heading(text: str, size: float, bold: bool, body_size: float) -> bool:
    """Decide whether one line of text looks like a heading."""
    if len(text) > MAX_HEADING_CHARS or len(text.split()) > MAX_HEADING_WORDS:
        return False
    if _DOT_LEADER.search(text):
        return False  # table-of-contents entry: "4 Framework ........ 12"
    if _SECTION_NUMBER.match(text):
        return bold or size >= body_size + 1.5
    if not re.search(r"[A-Za-z]", text):
        return False  # numbers, symbols, table cells
    if text.endswith((",", ";")):
        return False
    # A bold phrase wrapping mid-sentence: starts lowercase or ends on a connector word.
    if text[0].islower() or _DANGLING_WORD.search(text):
        return False
    if text.endswith(".") and len(text.split()) > 3:
        return False  # a bold sentence is emphasis, not a heading
    bigger = size >= body_size * 1.2 and size >= body_size + 1.5
    return bigger or (bold and size >= body_size - 0.5)


def _join_lines(lines: list[str]) -> str:
    """Join wrapped lines into one paragraph string."""
    text = ""
    for line in lines:
        if not text:
            text = line
        elif text.endswith("-") and len(text) > 1 and text[-2].isalpha():
            text += line  # "risk-" + "based" -> "risk-based"
        else:
            text += " " + line
    return text


def parse_pdf(path: Path) -> tuple[list[Paragraph], int]:
    """Parse a PDF. Returns (paragraphs, page_count)."""
    with pymupdf.open(path) as doc:
        page_count = doc.page_count
        lines = _extract_lines(doc)

    body_size = _body_size(lines)
    lines = _remove_headers_footers(lines, page_count)
    lines = _remove_toc_pages(lines)

    paragraphs: list[Paragraph] = []
    heading: str | None = None
    heading_parts: list[str] = []
    para_lines: list[str] = []
    para_page = 0
    para_key: tuple[int, int] | None = None  # (page, block) of current paragraph
    number_prefix = ""  # a lone paragraph number like "3.2.1" waiting for its text

    def flush() -> None:
        nonlocal para_lines, number_prefix
        if para_lines:
            text = _join_lines(para_lines)
            if _SECTION_NUMBER.match(text):
                number_prefix = text  # attach to the next paragraph
            else:
                if number_prefix:
                    text = f"{number_prefix} {text}"
                    number_prefix = ""
                paragraphs.append(Paragraph(para_page, heading, text))
        para_lines = []

    last_heading_style: tuple[int, float] | None = None  # (page, size) of last heading line

    for line in lines:
        if is_heading(line.text, line.size, line.bold, body_size):
            flush()
            # Merge only adjacent heading lines with the same page and size
            # ("3.2" + "Policies, ..."); otherwise the newer heading wins.
            style = (line.page, line.size)
            if style != last_heading_style or len(heading_parts) >= 3:
                heading_parts = []
            heading_parts.append(line.text)
            last_heading_style = style
            continue
        last_heading_style = None

        if heading_parts:
            heading = " ".join(heading_parts)[:200]
            heading_parts = []
            number_prefix = ""

        key = (line.page, line.block)
        if key != para_key:
            flush()
            para_key = key
            para_page = line.page
        para_lines.append(line.text)

    flush()
    return paragraphs, page_count
