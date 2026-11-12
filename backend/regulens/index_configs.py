"""Named chunk-index configurations.

Every way of chunking/embedding the corpus gets a name, and its chunks are
stored under that name in the `chunks` table. This lets several variants
live side by side, so the Phase 4 experiments can compare them without
re-ingesting, and every eval result can say exactly which index it used.
"""

from dataclasses import dataclass, replace

from regulens.chunking import ChunkConfig

# Annual reports are glossy: KPI call-outs, photo captions and director names
# get detected as "headings", which shatters the text into tiny sections
# (median 117 tokens in our first ingest). For them we merge any section
# under 200 tokens into the next one. MAS guidelines keep strict sections,
# because their headings are real ("3.2 Policies, Standards and Procedures").
REPORT_MIN_SECTION_TOKENS = 200


@dataclass(frozen=True)
class IndexConfig:
    name: str
    chunk: ChunkConfig
    # Prepend "<document title> | <section heading>" to the text before embedding.
    heading_in_embedding: bool = False

    def chunk_for(self, doc_type: str) -> ChunkConfig:
        """Chunk settings for one document type."""
        if doc_type == "annual_report":
            return replace(self.chunk, min_section_tokens=REPORT_MIN_SECTION_TOKENS)
        return self.chunk


INDEX_CONFIGS: dict[str, IndexConfig] = {
    cfg.name: cfg
    for cfg in [
        IndexConfig("baseline", ChunkConfig(chunk_size=600, overlap=100)),
    ]
}


def get_index_config(name: str) -> IndexConfig:
    try:
        return INDEX_CONFIGS[name]
    except KeyError:
        raise ValueError(f"Unknown index '{name}'. Known: {sorted(INDEX_CONFIGS)}") from None
