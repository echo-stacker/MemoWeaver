from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from memoweaver.config import MemoWeaverConfig

WIKI_DIRECTORIES = [
    "raw/articles",
    "raw/papers",
    "raw/transcripts",
    "raw/assets",
    "entities",
    "concepts",
    "comparisons",
    "queries",
]


@dataclass(frozen=True)
class WikiInitResult:
    wiki_path: Path
    created_files: tuple[Path, ...]
    created_directories: tuple[Path, ...]


def init_wiki(wiki_path: str | Path, domain: str | None = None) -> WikiInitResult:
    """Create the minimal MemoWeaver wiki layout.

    Existing files are preserved so the command is safe to run repeatedly.
    """

    config = MemoWeaverConfig.default(wiki_path, domain=domain)
    root = config.wiki_path
    root.mkdir(parents=True, exist_ok=True)

    created_directories: list[Path] = []
    for relative_directory in WIKI_DIRECTORIES:
        directory = root / relative_directory
        existed = directory.exists()
        directory.mkdir(parents=True, exist_ok=True)
        if not existed:
            created_directories.append(directory)

    created_files: list[Path] = []
    files = {
        root / "SCHEMA.md": _schema_content(),
        root / "index.md": _index_content(config),
        root / "log.md": _log_content(),
    }
    for path, content in files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created_files.append(path)

    return WikiInitResult(
        wiki_path=root,
        created_files=tuple(created_files),
        created_directories=tuple(created_directories),
    )


def _schema_content() -> str:
    return """# MemoWeaver Wiki Schema

This wiki is maintained by MemoWeaver.

## Top-level directories

- `raw/` — immutable source material grouped by source type.
- `entities/` — durable pages for people, organizations, products, and other named entities.
- `concepts/` — durable pages for reusable ideas, topics, and themes.
- `comparisons/` — synthesis pages comparing entities or concepts.
- `queries/` — valuable question-answer or synthesis outputs worth preserving.

## Core files

- `SCHEMA.md` — structure and conventions for this wiki.
- `index.md` — human-readable entry point.
- `log.md` — chronological maintenance log.
"""


def _index_content(config: MemoWeaverConfig) -> str:
    return f"""# MemoWeaver Wiki Index

Domain: {config.domain}

## Sections

- [[SCHEMA]]
- [[log]]
- Entities: `entities/`
- Concepts: `concepts/`
- Comparisons: `comparisons/`
- Queries: `queries/`
"""


def _log_content() -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"""# MemoWeaver Maintenance Log

- {timestamp} — Wiki initialized.
"""
