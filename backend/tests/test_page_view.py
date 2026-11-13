"""Tests for the source page view (GET /sources/{id}/pages/{page})."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from regulens import main
from regulens.page_view import cited_flags, split_label
from tests.pdf_factory import TextItem, make_pdf


@pytest.mark.parametrize(
    ("text", "label", "body"),
    [
        (
            "4.1.1 The FI should establish a framework.",
            "4.1.1",
            "The FI should establish a framework.",
        ),
        (
            "3.6. Local senior management remains accountable.",
            "3.6.",
            "Local senior management remains accountable.",
        ),
        ("12. Banks must report.", "12.", "Banks must report."),
        ("(g) ensuring the necessary competence", "(g)", "ensuring the necessary competence"),
        ("(iv) testing", "(iv)", "testing"),
        ("The FI should act within 1 hour.", None, "The FI should act within 1 hour."),
        ("2025 was a good year", None, "2025 was a good year"),  # a bare year is not a label
    ],
)
def test_split_label(text: str, label: str | None, body: str) -> None:
    assert split_label(text) == (label, body)


def test_cited_flags_prefers_paragraph_containing_the_quote() -> None:
    texts = ["Intro text about scope.", "The FI should notify MAS within 1 hour.", "Other."]
    assert cited_flags(texts, "notify  MAS within 1 hour") == [False, True, False]


def test_cited_flags_marks_every_paragraph_of_a_spanning_quote() -> None:
    texts = [
        "First part of a long requirement here.",
        "second part continues the rule.",
        "Unrelated.",
    ]
    quote = "First part of a long requirement here. second part continues the rule."
    assert cited_flags(texts, quote) == [True, True, False]


def test_cited_flags_falls_back_to_word_overlap_and_ignores_weak_matches() -> None:
    texts = [
        "Penetration tests must run at least annually on internet systems.",
        "Board oversight.",
    ]
    assert cited_flags(texts, "penetration tests at least annually") == [True, False]
    assert cited_flags(texts, "capital adequacy ratio") == [False, False]
    assert cited_flags(texts, None) == [False, False]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    raw = tmp_path / "raw"
    raw.mkdir()
    make_pdf(
        raw / "mas_test.pdf",
        pages=[
            [TextItem("4.1.1 The FI should establish a risk management framework.")],
            [
                TextItem("5.2.1 Board oversight is required for material systems."),
                TextItem(
                    "5.2.2 The FI should notify MAS within 1 hour of discovering an incident."
                ),
            ],
        ],
    )
    csv = tmp_path / "sources.csv"
    csv.write_text(
        "id,title,publisher,url,date_downloaded,doc_type\n"
        "mas_test,Test Guidelines,Monetary Authority of Singapore,https://example.org/t.pdf,"
        "2026-11-12,regulation\n"
        "mas_missing,Missing,Monetary Authority of Singapore,https://example.org/m.pdf,"
        "2026-11-12,regulation\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "RAW_DIR", raw)
    monkeypatch.setattr(main, "SOURCES_CSV", csv)
    return TestClient(main.app)


def test_page_flags_the_cited_paragraph_and_splits_labels(client: TestClient) -> None:
    body = client.get(
        "/sources/mas_test/pages/2", params={"quote": "notify MAS within 1 hour"}
    ).json()
    assert body["page"] == 2 and body["page_count"] == 2 and body["cited_found"] is True
    assert [(p["label"], p["cited"]) for p in body["paragraphs"]] == [
        ("5.2.1", False),
        ("5.2.2", True),
    ]
    assert body["paragraphs"][1]["text"].startswith("The FI should notify MAS")


def test_page_moves_to_where_a_spanning_citation_quote_is(client: TestClient) -> None:
    body = client.get(
        "/sources/mas_test/pages/1", params={"quote": "notify MAS within 1 hour", "through": 2}
    ).json()
    assert body["page"] == 2 and body["cited_found"] is True


def test_page_without_quote_shows_nothing_cited(client: TestClient) -> None:
    body = client.get("/sources/mas_test/pages/1").json()
    assert body["cited_found"] is False
    assert body["paragraphs"][0]["label"] == "4.1.1"


@pytest.mark.parametrize(
    "path",
    ["/sources/nope/pages/1", "/sources/mas_missing/pages/1", "/sources/mas_test/pages/9"],
)
def test_page_not_found_cases(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
