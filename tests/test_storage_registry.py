from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.storage import SourceRegistry, initialize_state
from memoweaver.wiki import init_wiki


def test_initialize_state_creates_file_based_state_layout(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path, domain="Storage test")

    state = initialize_state(wiki_path)

    assert state.state_path == wiki_path / ".wiki-state"
    assert (state.state_path / "sources.json").exists()
    assert (state.state_path / "ingest-history.jsonl").exists()
    assert (state.state_path / "llm-cache.json").exists()

    sources = json.loads((state.state_path / "sources.json").read_text(encoding="utf-8"))
    assert sources == {"schema_version": 1, "sources": []}
    assert (state.state_path / "ingest-history.jsonl").read_text(encoding="utf-8") == ""
    assert json.loads((state.state_path / "llm-cache.json").read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "entries": {},
    }


def test_source_registry_registers_file_and_detects_duplicate_content(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# Durable Knowledge\n\nMemoWeaver stores source history.\n", encoding="utf-8")
    init_wiki(wiki_path)

    registry = SourceRegistry.open(wiki_path)
    first = registry.register_file(source_path, kind="markdown", title="Durable Knowledge")
    second = registry.register_file(source_path, kind="markdown", title="Durable Knowledge")

    assert first.created is True
    assert second.created is False
    assert first.record.source_id == second.record.source_id
    assert first.record.sha256 == second.record.sha256
    assert second.record.ingest_count == 2

    records = registry.list_sources()
    assert len(records) == 1
    assert records[0].title == "Durable Knowledge"
    assert records[0].kind == "markdown"
    assert records[0].uri.endswith("note.md")

    history_lines = (wiki_path / ".wiki-state" / "ingest-history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 2
    assert json.loads(history_lines[0])["event"] == "source_registered"
    assert json.loads(history_lines[1])["event"] == "source_seen"


def test_source_registry_finds_existing_record_by_sha256(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_text("same content", encoding="utf-8")
    second_path.write_text("same content", encoding="utf-8")
    init_wiki(wiki_path)

    registry = SourceRegistry.open(wiki_path)
    first = registry.register_file(first_path, kind="text")
    existing = registry.find_by_sha256(first.record.sha256)
    second = registry.register_file(second_path, kind="text")

    assert existing is not None
    assert existing.source_id == first.record.source_id
    assert second.created is False
    assert second.record.source_id == first.record.source_id
    assert len(registry.list_sources()) == 1


def test_cli_sources_register_initializes_state_and_reports_duplicate(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# CLI source\n", encoding="utf-8")
    init_wiki(wiki_path)
    runner = CliRunner()

    first = runner.invoke(
        cli,
        ["sources", "register", str(source_path), "--wiki", str(wiki_path), "--kind", "markdown", "--title", "CLI source"],
    )
    second = runner.invoke(
        cli,
        ["sources", "register", str(source_path), "--wiki", str(wiki_path), "--kind", "markdown", "--title", "CLI source"],
    )

    assert first.exit_code == 0
    assert "Registered source" in first.output
    assert "source_id=" in first.output
    assert second.exit_code == 0
    assert "Duplicate source" in second.output
    assert (wiki_path / ".wiki-state" / "sources.json").exists()
