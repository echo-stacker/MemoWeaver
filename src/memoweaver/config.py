from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoWeaverConfig:
    """Runtime configuration for a MemoWeaver wiki."""

    wiki_path: Path
    domain: str = "General knowledge"
    llm_provider: str = "none"

    @classmethod
    def default(cls, wiki_path: str | Path, domain: str | None = None) -> "MemoWeaverConfig":
        return cls(
            wiki_path=Path(wiki_path),
            domain=domain or "General knowledge",
            llm_provider="none",
        )
