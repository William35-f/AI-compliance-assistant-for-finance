"""The source document registry: data/sources.csv.

sources.csv is the single list of documents ReguLens knows about. Each row's
PDF must be saved as data/raw/<id>.pdf. The ingestion script (Phase 1) and
the eval scripts (Phase 3) read this registry, so we validate it strictly.
"""

import csv
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, ValidationError

COLUMNS = ["id", "title", "publisher", "url", "date_downloaded", "doc_type"]
DocType = Literal["regulation", "annual_report"]


class Source(BaseModel):
    # Lowercase letters, digits and underscores, e.g. "mas_trm_2021", "ar_dbs_fy2025".
    id: str = Field(pattern=r"^[a-z0-9_]+$", max_length=64)
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    url: AnyHttpUrl
    date_downloaded: date  # must be YYYY-MM-DD
    doc_type: DocType

    def pdf_path(self, raw_dir: Path) -> Path:
        return raw_dir / f"{self.id}.pdf"


class SourcesError(ValueError):
    """Raised when sources.csv has one or more invalid rows."""


def load_sources(csv_path: Path) -> list[Source]:
    """Read and validate sources.csv. Collects every problem before raising.

    Uses utf-8-sig so a file saved by Excel (which adds a BOM) still works.
    """
    errors: list[str] = []
    sources: list[Source] = []
    seen_ids: set[str] = set()

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise SourcesError(f"Header must be exactly {COLUMNS}, got {reader.fieldnames}")

        # Row 1 is the header, so data starts at line 2.
        for line_no, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue  # ignore blank lines
            cleaned = {key: (value or "").strip() for key, value in row.items()}
            try:
                source = Source(**cleaned)
            except ValidationError as exc:
                for err in exc.errors():
                    field = ".".join(str(part) for part in err["loc"])
                    errors.append(f"line {line_no}: {field}: {err['msg']}")
                continue
            if source.id in seen_ids:
                errors.append(f"line {line_no}: duplicate id '{source.id}'")
                continue
            seen_ids.add(source.id)
            sources.append(source)

    if errors:
        raise SourcesError("Invalid sources.csv:\n  " + "\n  ".join(errors))
    return sources


def check_files(sources: list[Source], raw_dir: Path) -> list[str]:
    """Compare the registry with the PDFs on disk. Returns a list of problems."""
    problems: list[str] = []
    for source in sources:
        if not source.pdf_path(raw_dir).is_file():
            problems.append(f"missing file for '{source.id}': expected {source.pdf_path(raw_dir)}")

    known = {source.id for source in sources}
    for pdf in sorted(raw_dir.glob("*.pdf")):
        if pdf.stem not in known:
            problems.append(f"'{pdf.name}' is in {raw_dir} but has no row in sources.csv")
    return problems
