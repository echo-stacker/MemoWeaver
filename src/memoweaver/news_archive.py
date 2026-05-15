from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memoweaver.ingest import IngestFileResult, ingest_file
from memoweaver.parser import ParsedDocument, parse_wiki_raw_source
from memoweaver.storage import SourceRecord

NEWS_ARCHIVE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class NewsArchiveIngestResult:
    """Summary for importing one normalized market-news archive into a wiki."""

    source: str
    date: str
    archive_path: Path
    title: str
    ingest: IngestFileResult
    document: ParsedDocument

    @property
    def record(self) -> SourceRecord:
        return self.ingest.record

    @property
    def raw_path(self) -> Path:
        return self.ingest.raw_path

    @property
    def metadata_path(self) -> Path:
        return self.ingest.metadata_path

    @property
    def created(self) -> bool:
        return self.ingest.created

    @property
    def item_count(self) -> int:
        return int(self.document.metadata.get("item_count") or 0)

    @property
    def block_count(self) -> int:
        return len(self.document.blocks)

    @property
    def chunk_count(self) -> int:
        return len(self.document.chunks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": NEWS_ARCHIVE_SCHEMA_VERSION,
            "source": self.source,
            "date": self.date,
            "title": self.title,
            "source_id": self.record.source_id,
            "kind": self.record.kind,
            "created": self.created,
            "archive_path": str(self.archive_path),
            "raw_path": str(self.raw_path),
            "metadata_path": str(self.metadata_path),
            "item_count": self.item_count,
            "block_count": self.block_count,
            "chunk_count": self.chunk_count,
            "document_title": self.document.title,
        }


def ingest_news_archive(
    archive_repo: str | Path,
    *,
    wiki_path: str | Path,
    date: str,
    source: str = "cls",
    title: str | None = None,
) -> NewsArchiveIngestResult:
    """Ingest and parse one normalized daily news archive from an archive repo.

    The function intentionally stops after local ingest+parse. LLM extraction and
    page writing remain explicit follow-up stages so callers can decide whether to
    spend model calls and how to resolve generated pages.
    """

    repo = Path(archive_repo)
    archive_path = resolve_news_archive_path(repo, date=date, source=source)
    effective_title = title or _default_title(repo, archive_path=archive_path, date=date, source=source)
    ingest_result = ingest_file(archive_path, wiki_path=wiki_path, title=effective_title)
    document = parse_wiki_raw_source(ingest_result.raw_path)
    return NewsArchiveIngestResult(
        source=source,
        date=date,
        archive_path=archive_path,
        title=effective_title,
        ingest=ingest_result,
        document=document,
    )


def resolve_news_archive_path(archive_repo: str | Path, *, date: str, source: str = "cls") -> Path:
    """Resolve a normalized JSONL archive path from registry config or layout defaults."""

    repo = Path(archive_repo)
    year = date[:4]
    registry_source = _load_registry_source(repo, source)
    pattern = str(registry_source.get("data_glob") or "sources/{source_id}/data/{year}/{date}.jsonl")
    rel_path = pattern.format(source_id=source, year=year, date=date)
    path = repo / rel_path
    if not path.exists():
        raise FileNotFoundError(f"News archive not found for source={source!r} date={date!r}: {path}")
    return path


def _default_title(repo: Path, *, archive_path: Path, date: str, source: str) -> str:
    source_name = str(_load_registry_source(repo, source).get("name") or "").strip()
    if not source_name:
        source_name = _peek_source_name(archive_path) or source
    return f"{source_name}快讯 {date}"


def _load_registry_source(repo: Path, source: str) -> dict[str, Any]:
    registry_path = repo / "manifests" / "source_registry.json"
    if not registry_path.exists():
        return {}
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, dict):
        return {}
    entry = sources.get(source)
    return dict(entry) if isinstance(entry, dict) else {}


def _peek_source_name(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return str(payload.get("source_name") or "").strip()
    return ""
