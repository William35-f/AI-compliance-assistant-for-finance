"""Tests for the sources.csv registry loader and file checker."""

from pathlib import Path

import pytest

from regulens.config import SOURCES_CSV
from regulens.sources import COLUMNS, SourcesError, check_files, load_sources

HEADER = ",".join(COLUMNS)
GOOD_ROW = "mas_trm_2021,Technology Risk Management Guidelines,MAS,https://www.mas.gov.sg/x,2026-11-12,regulation"


def write_csv(tmp_path: Path, *rows: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / "sources.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding=encoding)
    return path


def test_loads_valid_row(tmp_path: Path) -> None:
    sources = load_sources(write_csv(tmp_path, GOOD_ROW))
    assert len(sources) == 1
    assert sources[0].id == "mas_trm_2021"
    assert sources[0].doc_type == "regulation"


def test_accepts_excel_bom(tmp_path: Path) -> None:
    # Excel's "CSV UTF-8" format starts the file with a byte-order mark.
    sources = load_sources(write_csv(tmp_path, GOOD_ROW, encoding="utf-8-sig"))
    assert len(sources) == 1


def test_skips_blank_lines(tmp_path: Path) -> None:
    assert len(load_sources(write_csv(tmp_path, GOOD_ROW, ",,,,,", ""))) == 1


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(SourcesError, match="duplicate id"):
        load_sources(write_csv(tmp_path, GOOD_ROW, GOOD_ROW))


@pytest.mark.parametrize(
    ("bad_row", "expected"),
    [
        (GOOD_ROW.replace("regulation", "blog_post"), "doc_type"),
        (GOOD_ROW.replace("2026-11-12", "12/11/2026"), "date_downloaded"),
        (GOOD_ROW.replace("mas_trm_2021", "MAS TRM"), "id"),
        (GOOD_ROW.replace("https://www.mas.gov.sg/x", "not a url"), "url"),
    ],
)
def test_rejects_invalid_fields(tmp_path: Path, bad_row: str, expected: str) -> None:
    with pytest.raises(SourcesError, match=expected):
        load_sources(write_csv(tmp_path, bad_row))


def test_rejects_wrong_header(tmp_path: Path) -> None:
    path = tmp_path / "sources.csv"
    path.write_text("id,name\n", encoding="utf-8")
    with pytest.raises(SourcesError, match="Header"):
        load_sources(path)


def test_check_files_reports_missing_and_unregistered(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "stray_file.pdf").write_bytes(b"%PDF-1.4")
    sources = load_sources(write_csv(tmp_path, GOOD_ROW))

    problems = check_files(sources, raw_dir)

    assert any("missing file for 'mas_trm_2021'" in p for p in problems)
    assert any("stray_file.pdf" in p for p in problems)


def test_committed_sources_csv_is_valid() -> None:
    """The real data/sources.csv in the repo must always parse."""
    load_sources(SOURCES_CSV)
