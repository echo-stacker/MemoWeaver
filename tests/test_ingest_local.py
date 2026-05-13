from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.ingest import ingest_file
from memoweaver.storage import SourceRegistry
from memoweaver.wiki import init_wiki


def test_ingest_markdown_copies_raw_source_and_metadata(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# First Note\n\nMemoWeaver should keep raw sources.\n", encoding="utf-8")
    init_wiki(wiki_path)

    result = ingest_file(source_path, wiki_path=wiki_path, title="First Note")

    assert result.created is True
    assert result.record.kind == "markdown"
    assert result.raw_path == wiki_path / "raw" / "articles" / f"{result.record.source_id}.md"
    assert result.raw_path.read_text(encoding="utf-8") == source_path.read_text(encoding="utf-8")

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 1
    assert metadata["source_id"] == result.record.source_id
    assert metadata["sha256"] == result.record.sha256
    assert metadata["title"] == "First Note"
    assert metadata["original_path"].endswith("note.md")
    assert metadata["raw_path"].endswith(f"{result.record.source_id}.md")

    registry = SourceRegistry.open(wiki_path)
    assert registry.find_by_sha256(result.record.sha256) is not None


def test_ingest_text_uses_txt_extension_and_text_kind(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "plain.txt"
    source_path.write_text("Plain text source\n", encoding="utf-8")
    init_wiki(wiki_path)

    result = ingest_file(source_path, wiki_path=wiki_path)

    assert result.record.kind == "text"
    assert result.raw_path.name == f"{result.record.source_id}.txt"
    assert result.raw_path.read_text(encoding="utf-8") == "Plain text source\n"


def test_ingest_duplicate_does_not_rewrite_existing_raw_source(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# Stable raw source\n", encoding="utf-8")
    init_wiki(wiki_path)

    first = ingest_file(source_path, wiki_path=wiki_path, title="Original")
    first.raw_path.write_text("user edited raw copy should not be overwritten\n", encoding="utf-8")
    second = ingest_file(source_path, wiki_path=wiki_path, title="Original")

    assert second.created is False
    assert second.raw_path == first.raw_path
    assert second.metadata_path == first.metadata_path
    assert second.raw_path.read_text(encoding="utf-8") == "user edited raw copy should not be overwritten\n"
    assert second.record.ingest_count == 2


def test_ingest_rejects_unsupported_file_extension(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "data.csv"
    source_path.write_text("a,b\n1,2\n", encoding="utf-8")
    init_wiki(wiki_path)

    try:
        ingest_file(source_path, wiki_path=wiki_path)
    except ValueError as exc:
        assert "Unsupported local ingest type" in str(exc)
    else:
        raise AssertionError("CSV ingest should not be accepted in the Markdown/TXT MVP")


def test_cli_ingest_imports_markdown_and_reports_duplicate(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# CLI ingest\n", encoding="utf-8")
    init_wiki(wiki_path)
    runner = CliRunner()

    first = runner.invoke(cli, ["ingest", str(source_path), "--wiki", str(wiki_path), "--title", "CLI ingest"])
    second = runner.invoke(cli, ["ingest", str(source_path), "--wiki", str(wiki_path), "--title", "CLI ingest"])

    assert first.exit_code == 0
    assert "Ingested source" in first.output
    assert "raw_path=" in first.output
    assert second.exit_code == 0
    assert "Duplicate source" in second.output

    records = SourceRegistry.open(wiki_path).list_sources()
    assert len(records) == 1
    raw_path = wiki_path / "raw" / "articles" / f"{records[0].source_id}.md"
    assert raw_path.exists()
