from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from memoweaver.storage import SourceRecord, SourceRegistry

INGEST_SCHEMA_VERSION = 1
SUPPORTED_LOCAL_KINDS = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}


@dataclass(frozen=True)
class IngestFileResult:
    """Result produced by the local-file ingestion MVP.

    The result exposes both the source-registry record and the raw-copy paths.
    Future parser/LLM modules should not guess where raw files live; they should
    consume this result or a registry lookup so storage layout changes stay local
    to the ingest module.
    """

    record: SourceRecord
    raw_path: Path
    metadata_path: Path
    created: bool


def ingest_file(source_path: str | Path, *, wiki_path: str | Path, title: str | None = None) -> IngestFileResult:
    """Import a local Markdown/TXT file into a MemoWeaver wiki.

    Phase 3 deliberately supports only local Markdown and plain text. URLs, PDFs,
    folder walks, and rich document extraction are separate concerns and should
    not be smuggled into this small path. Keeping this function narrow gives the
    project a reliable first ingestion contract:

    1. identify the source by content hash via `SourceRegistry`;
    2. copy a first-seen source into `raw/articles/` using a stable source id;
    3. write sidecar metadata that preserves provenance for later parser/LLM work;
    4. avoid overwriting raw files on duplicate content.
    """

    source = Path(source_path)
    wiki = Path(wiki_path)
    kind = infer_local_kind(source)

    registry = SourceRegistry.open(wiki)
    registration = registry.register_file(source, kind=kind, title=title)
    record = registration.record
    raw_path = _raw_path_for_record(wiki, source, record)
    metadata_path = _metadata_path_for_record(wiki, record)

    if registration.created:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, raw_path)
        _write_metadata(metadata_path, source=source, raw_path=raw_path, record=record)

    return IngestFileResult(
        record=record,
        raw_path=raw_path,
        metadata_path=metadata_path,
        created=registration.created,
    )


def infer_local_kind(source_path: str | Path) -> str:
    """Return the MemoWeaver source kind for a supported local file.

    The MVP rejects unknown suffixes instead of silently treating every file as
    text. That protects future contributors from debugging garbage parser input
    when someone accidentally points ingest at a PDF, spreadsheet, or binary.
    """

    suffix = Path(source_path).suffix.lower()
    try:
        return SUPPORTED_LOCAL_KINDS[suffix]
    except KeyError as exc:
        supported = ", ".join(sorted(SUPPORTED_LOCAL_KINDS))
        raise ValueError(f"Unsupported local ingest type: {suffix or '<no extension>'}. Supported: {supported}") from exc


def _raw_path_for_record(wiki_path: Path, source_path: Path, record: SourceRecord) -> Path:
    # Markdown and text are routed to raw/articles for now because they represent
    # authored textual source material. If later we add `raw/notes/`, only this
    # routing helper and the public documentation need to change.
    suffix = ".md" if record.kind == "markdown" else source_path.suffix.lower()
    return wiki_path / "raw" / "articles" / f"{record.source_id}{suffix}"


def _metadata_path_for_record(wiki_path: Path, record: SourceRecord) -> Path:
    return wiki_path / "raw" / "articles" / f"{record.source_id}.metadata.json"


def _write_metadata(metadata_path: Path, *, source: Path, raw_path: Path, record: SourceRecord) -> None:
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": INGEST_SCHEMA_VERSION,
                "source_id": record.source_id,
                "kind": record.kind,
                "sha256": record.sha256,
                "title": record.title,
                "original_uri": record.uri,
                "original_path": str(source.expanduser().resolve()),
                "raw_path": str(raw_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
