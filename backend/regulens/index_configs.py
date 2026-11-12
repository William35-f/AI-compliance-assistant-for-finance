"""Named chunk-index configurations.

Every way of chunking/embedding the corpus gets a name, and its chunks are
stored under that name in the `chunks` table. This lets several variants
live side by side, so the Phase 4 experiments can compare them without
re-ingesting, and every eval result can say exactly which index it used.
"""

from dataclasses import dataclass

from regulens.chunking import ChunkConfig


@dataclass(frozen=True)
class IndexConfig:
    name: str
    chunk: ChunkConfig
    # Prepend "<document title> | <section heading>" to the text before embedding.
    heading_in_embedding: bool = False


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
