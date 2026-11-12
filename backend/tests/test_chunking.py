"""Tests for the section-aware chunker."""

import pytest

from regulens.chunking import ChunkConfig, approx_token_count, chunk_paragraphs
from regulens.pdf_parser import Paragraph


def sentences(prefix: str, n: int, words: int = 9) -> str:
    """n distinct sentences of `words` words + a full stop (= words + 1 tokens each)."""
    return " ".join(
        f"{prefix.capitalize()} sentence {i} " + " ".join(["word"] * (words - 3)) + "."
        for i in range(n)
    )


def section(heading: str, text: str, page: int = 1) -> Paragraph:
    return Paragraph(page=page, heading=heading, text=text)


def test_empty_input_gives_no_chunks() -> None:
    assert chunk_paragraphs([]) == []


def test_small_section_is_one_chunk() -> None:
    chunks = chunk_paragraphs([section("1 Intro", sentences("alpha", 6))])
    assert len(chunks) == 1
    assert chunks[0].heading == "1 Intro"
    assert chunks[0].index == 0


def test_chunks_respect_max_size() -> None:
    config = ChunkConfig(chunk_size=50, overlap=10, min_section_tokens=1)
    chunks = chunk_paragraphs([section("A", sentences("alpha", 30))], config)
    assert len(chunks) > 1
    assert all(c.token_count <= 50 for c in chunks)


def test_consecutive_chunks_overlap_by_whole_sentences() -> None:
    config = ChunkConfig(chunk_size=50, overlap=20, min_section_tokens=1)
    chunks = chunk_paragraphs([section("A", sentences("alpha", 30))], config)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        first_sentence_of_next = nxt.text.split(". ")[0] + "."
        assert first_sentence_of_next in prev.text  # next chunk starts with repeated text
        assert nxt.text.startswith("Alpha sentence")  # ...and at a sentence boundary


def test_zero_overlap_means_no_repeated_sentences() -> None:
    config = ChunkConfig(chunk_size=50, overlap=0, min_section_tokens=1)
    chunks = chunk_paragraphs([section("A", sentences("alpha", 30))], config)
    joined = " ".join(c.text for c in chunks)
    assert joined.count("Alpha sentence 5 ") == 1


def test_never_mixes_sections() -> None:
    config = ChunkConfig(chunk_size=500, overlap=50, min_section_tokens=1)
    paragraphs = [
        section("1 Alpha", sentences("alpha", 5)),
        section("2 Beta", sentences("beta", 5)),
    ]
    chunks = chunk_paragraphs(paragraphs, config)
    assert [c.heading for c in chunks] == ["1 Alpha", "2 Beta"]
    assert "Beta" not in chunks[0].text
    assert "Alpha" not in chunks[1].text


def test_tiny_section_merges_into_next() -> None:
    config = ChunkConfig(chunk_size=500, overlap=0, min_section_tokens=20)
    paragraphs = [section("Cover", "Guidelines 2021"), section("1 Intro", sentences("alpha", 5))]
    chunks = chunk_paragraphs(paragraphs, config)
    assert len(chunks) == 1
    assert chunks[0].heading == "1 Intro"
    assert chunks[0].text.startswith("Guidelines 2021")


def test_tracks_page_range() -> None:
    config = ChunkConfig(chunk_size=500, overlap=0, min_section_tokens=1)
    paragraphs = [
        section("A", sentences("alpha", 3), page=4),
        section("A", sentences("more", 3), page=5),
    ]
    chunks = chunk_paragraphs(paragraphs, config)
    assert (chunks[0].page_start, chunks[0].page_end) == (4, 5)


def test_paragraph_breaks_become_newlines() -> None:
    config = ChunkConfig(chunk_size=500, overlap=0, min_section_tokens=1)
    paragraphs = [section("A", "First paragraph."), section("A", "Second paragraph.")]
    assert chunk_paragraphs(paragraphs, config)[0].text == "First paragraph.\nSecond paragraph."


def test_very_long_sentence_is_split_by_words() -> None:
    config = ChunkConfig(chunk_size=40, overlap=0, min_section_tokens=1)
    table_row = " ".join(f"cell{i}" for i in range(200))  # one huge "sentence", no full stops
    chunks = chunk_paragraphs([section("Table", table_row)], config)
    assert len(chunks) >= 5
    assert all(c.token_count <= 40 for c in chunks)
    assert " ".join(c.text for c in chunks) == table_row  # nothing lost


def test_custom_token_counter_is_used() -> None:
    def count_chars(text: str) -> int:
        return len(text)

    config = ChunkConfig(chunk_size=100, overlap=0, min_section_tokens=1)
    chunks = chunk_paragraphs([section("A", sentences("alpha", 20))], config, count_chars)
    assert all(c.token_count <= 100 for c in chunks)


def test_chunk_indices_are_sequential_across_sections() -> None:
    config = ChunkConfig(chunk_size=30, overlap=0, min_section_tokens=1)
    paragraphs = [section("A", sentences("alpha", 10)), section("B", sentences("beta", 10))]
    chunks = chunk_paragraphs(paragraphs, config)
    assert [c.index for c in chunks] == list(range(len(chunks)))


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, 100), (100, -1)])
def test_invalid_config_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        ChunkConfig(chunk_size=size, overlap=overlap)


def test_approx_token_count() -> None:
    # The / FI / ' / s / board / , / ( / 2021 / ) / .
    assert approx_token_count("The FI's board, (2021).") == 10
