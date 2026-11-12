"""Tests for the PDF parser: headings, headers/footers, pages, line joining."""

from pathlib import Path

import pytest

from regulens.pdf_parser import is_heading, parse_pdf
from tests.pdf_factory import TextItem, make_pdf

BODY = 11


@pytest.mark.parametrize(
    ("text", "size", "bold", "expected"),
    [
        ("1 Introduction", 18, False, True),  # clearly bigger than body text
        ("3.2 Policies, Standards and Procedures", BODY, True, True),  # bold, body size
        ("3.2", BODY, True, True),  # lone section number (merged with next line later)
        ("The FI should establish policies.", BODY, False, False),  # plain body text
        ("Senior management is responsible for:", BODY, False, False),
        ("This bold sentence is emphasis, not a heading.", BODY, True, False),
        ("policies, and practices across the organisation", BODY, True, False),  # lowercase start
        ("MAS would like to express our appreciation to the", BODY, True, False),  # dangling
        ("4 Framework ............................ 12", BODY, True, False),  # TOC line
        ("12,345", 18, True, False),  # number only
        ("A" * 130, 18, True, False),  # far too long
    ],
)
def test_is_heading(text: str, size: float, bold: bool, expected: bool) -> None:
    assert is_heading(text, size, bold, BODY) is expected


@pytest.fixture
def guideline_pdf(tmp_path: Path) -> Path:
    """Four pages with a running header, page-number footers and two sections."""
    body = "The FI should identify threats and vulnerabilities in its IT environment."
    return make_pdf(
        tmp_path / "guideline.pdf",
        header="ACME RISK GUIDELINES",
        footer_page_numbers=True,
        pages=[
            [
                TextItem("1 Introduction", size=18),
                TextItem(f"{body}\nThis paragraph wraps onto a second line."),
            ],
            [
                TextItem("3.2", bold=True),
                TextItem("Risk Assessment", bold=True),
                TextItem("3.2.1"),
                TextItem("Use a risk-\nbased approach for every system."),
            ],
            [TextItem("Continued text that still belongs to section 3.2 on the next page.")],
            [TextItem("4 Monitoring", size=18), TextItem("Monitor controls regularly.")],
        ],
    )


def test_removes_running_header_and_page_numbers(guideline_pdf: Path) -> None:
    paragraphs, page_count = parse_pdf(guideline_pdf)
    assert page_count == 4
    all_text = " ".join(p.text for p in paragraphs)
    assert "ACME RISK GUIDELINES" not in all_text
    assert not any(p.text.strip().isdigit() for p in paragraphs)


def test_assigns_nearest_heading_and_page(guideline_pdf: Path) -> None:
    paragraphs, _ = parse_pdf(guideline_pdf)
    by_text = {p.text: p for p in paragraphs}

    intro = next(p for p in paragraphs if p.text.startswith("The FI should identify"))
    assert intro.heading == "1 Introduction"
    assert intro.page == 1

    # "3.2" + "Risk Assessment" merge into one heading; the heading carries over to page 3.
    continued = next(p for p in paragraphs if p.text.startswith("Continued text"))
    assert continued.heading == "3.2 Risk Assessment"
    assert continued.page == 3

    assert by_text["Monitor controls regularly."].heading == "4 Monitoring"


def test_joins_wrapped_lines_and_paragraph_numbers(guideline_pdf: Path) -> None:
    paragraphs, _ = parse_pdf(guideline_pdf)
    texts = [p.text for p in paragraphs]
    # Lines of one block become one paragraph.
    assert any("environment. This paragraph wraps onto a second line." in t for t in texts)
    # A lone paragraph number is attached to the paragraph after it;
    # a line ending in a hyphen joins without a space.
    assert "3.2.1 Use a risk-based approach for every system." in texts


def test_drops_table_of_contents_pages(tmp_path: Path) -> None:
    toc = "\n".join(f"{i} Section {i} ................ {i + 2}" for i in range(1, 7))
    pdf = make_pdf(
        tmp_path / "toc.pdf",
        pages=[[TextItem("Contents", size=18), TextItem(toc)], [TextItem("Real body text.")]],
    )
    paragraphs, _ = parse_pdf(pdf)
    assert [p.text for p in paragraphs] == ["Real body text."]
    assert paragraphs[0].page == 2
