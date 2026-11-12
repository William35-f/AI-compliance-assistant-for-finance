"""Section-aware chunking with overlap.

Rules, in order of importance:
1. A chunk never mixes two sections (headings). A retrieved chunk then has one
   clear heading to cite, and its text is about one topic.
2. A chunk holds at most `chunk_size` tokens.
3. Consecutive chunks in a section share about `overlap` tokens (whole
   sentences), so a fact that straddles a boundary is fully present in at
   least one chunk.

We pack *sentences*, not characters, so chunks never start or end mid-sentence
(except when a single "sentence", e.g. a flattened table row, is longer than a
whole chunk and must be cut by words).
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from regulens.pdf_parser import Paragraph

TokenCounter = Callable[[str], int]

# Split after . ! ? when followed by whitespace and an uppercase letter, digit,
# bracket or quote. Imperfect for abbreviations like "e.g." but good enough.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'“‘])")


def approx_token_count(text: str) -> int:
    """Rough token count: words and punctuation marks. Used in tests and as a default."""
    return len(re.findall(r"\w+|[^\w\s]", text))


@dataclass(frozen=True)
class ChunkConfig:
    chunk_size: int = 600  # max tokens per chunk
    overlap: int = 100  # tokens shared with the previous chunk of the same section
    min_section_tokens: int = 40  # smaller sections are merged into the next one

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= self.overlap < self.chunk_size:
            raise ValueError("overlap must be >= 0 and smaller than chunk_size")


@dataclass(frozen=True)
class Chunk:
    index: int  # position within the document, 0-based
    heading: str | None
    text: str
    page_start: int
    page_end: int
    token_count: int


@dataclass(frozen=True)
class _Unit:
    """One sentence (or sentence piece) plus where it came from."""

    text: str
    page: int
    tokens: int
    new_paragraph: bool  # join with a newline instead of a space


def _split_long(text: str, max_tokens: int, count: TokenCounter) -> list[str]:
    """Cut text that is longer than max_tokens into word-based pieces."""
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split():
        if current and count(" ".join([*current, word])) > max_tokens:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _to_units(paragraphs: Sequence[Paragraph], max_tokens: int, count: TokenCounter) -> list[_Unit]:
    units: list[_Unit] = []
    for para in paragraphs:
        first = True
        for sentence in _SENTENCE_END.split(para.text):
            sentence = sentence.strip()
            if not sentence:
                continue
            tokens = count(sentence)
            pieces = (
                [sentence] if tokens <= max_tokens else _split_long(sentence, max_tokens, count)
            )
            for piece in pieces:
                units.append(_Unit(piece, para.page, count(piece), first))
                first = False
    return units


def _group_sections(
    paragraphs: Sequence[Paragraph], min_tokens: int, count: TokenCounter
) -> list[tuple[str | None, list[Paragraph]]]:
    """Group consecutive paragraphs by heading; merge tiny sections forward."""
    sections: list[tuple[str | None, list[Paragraph]]] = []
    for para in paragraphs:
        if sections and sections[-1][0] == para.heading:
            sections[-1][1].append(para)
        else:
            sections.append((para.heading, [para]))

    merged: list[tuple[str | None, list[Paragraph]]] = []
    carry: list[Paragraph] = []
    for heading, paras in sections:
        paras = carry + paras
        if sum(count(p.text) for p in paras) < min_tokens:
            carry = paras  # too small on its own: prepend to the next section
            continue
        merged.append((heading, paras))
        carry = []
    if carry:  # leftover tiny tail: attach to the last section, or keep alone
        if merged:
            merged[-1][1].extend(carry)
        else:
            merged.append((carry[-1].heading, carry))
    return merged


def _make_chunk(index: int, heading: str | None, units: list[_Unit], count: TokenCounter) -> Chunk:
    text = ""
    for unit in units:
        if not text:
            text = unit.text
        else:
            text += ("\n" if unit.new_paragraph else " ") + unit.text
    return Chunk(
        index=index,
        heading=heading,
        text=text,
        page_start=min(u.page for u in units),
        page_end=max(u.page for u in units),
        token_count=count(text),
    )


def chunk_paragraphs(
    paragraphs: Sequence[Paragraph],
    config: ChunkConfig | None = None,
    count_tokens: TokenCounter = approx_token_count,
) -> list[Chunk]:
    """Split a document's paragraphs into overlapping, section-aware chunks."""
    config = config or ChunkConfig()
    chunks: list[Chunk] = []
    for heading, paras in _group_sections(paragraphs, config.min_section_tokens, count_tokens):
        current: list[_Unit] = []
        current_tokens = 0
        for unit in _to_units(paras, config.chunk_size, count_tokens):
            if current and current_tokens + unit.tokens > config.chunk_size:
                chunks.append(_make_chunk(len(chunks), heading, current, count_tokens))
                # Start the next chunk with the last few sentences (the overlap).
                tail: list[_Unit] = []
                tail_tokens = 0
                for prev in reversed(current):
                    if tail_tokens + prev.tokens > config.overlap:
                        break
                    tail.insert(0, prev)
                    tail_tokens += prev.tokens
                current, current_tokens = tail, tail_tokens
                # If overlap + this unit would still be too big, drop overlap sentences.
                while current and current_tokens + unit.tokens > config.chunk_size:
                    current_tokens -= current.pop(0).tokens
            current.append(unit)
            current_tokens += unit.tokens
        if current:
            chunks.append(_make_chunk(len(chunks), heading, current, count_tokens))
    return chunks
