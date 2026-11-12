"""Build small PDFs with known structure for tests (no real documents needed)."""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

A4_WIDTH, A4_HEIGHT = 595, 842


@dataclass
class TextItem:
    text: str  # may contain "\n" for several lines in one block
    size: float = 11
    bold: bool = False


def make_pdf(
    path: Path,
    pages: list[list[TextItem]],
    header: str | None = None,
    footer_page_numbers: bool = False,
) -> Path:
    """Write a PDF where each page lists its text items top to bottom."""
    doc = pymupdf.open()
    for page_no, items in enumerate(pages, start=1):
        page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)
        if header:
            page.insert_text((50, 40), header, fontsize=9, fontname="helv")
        if footer_page_numbers:
            page.insert_text((290, 815), str(page_no), fontsize=9, fontname="helv")
        y = 120.0
        for item in items:
            font = "hebo" if item.bold else "helv"  # Helvetica-Bold / Helvetica
            line_count = item.text.count("\n") + 1
            page.insert_text((50, y), item.text, fontsize=item.size, fontname=font)
            y += item.size * 1.25 * line_count + 18  # gap so each item is its own block
    doc.save(path)
    doc.close()
    return path
