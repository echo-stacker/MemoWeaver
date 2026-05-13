from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.llm import LLMExtraction
from memoweaver.wiki import init_wiki
from memoweaver.wiki_writer import page_slug, write_extraction_pages


def _extraction() -> LLMExtraction:
    return LLMExtraction(
        source_id="src_demo",
        summary="MemoWeaver turns raw notes into maintained wiki pages.",
        entities=[{"name": "MemoWeaver", "type": "project", "description": "Headless LLM wiki maintainer"}],
        concepts=["LLM-native wiki", "Knowledge weaving"],
        claims=[{"text": "Parser output feeds extraction", "confidence": 0.8}],
        relations=[{"source": "Parser", "target": "LLM", "type": "feeds"}],
        suggested_pages=[{"title": "MemoWeaver Architecture", "reason": "central system overview"}],
    )


def test_page_slug_is_stable_for_wiki_filenames() -> None:
    assert page_slug("LLM-native Wiki!") == "llm-native-wiki"
    assert page_slug("  MemoWeaver Architecture  ") == "memoweaver-architecture"
    assert page_slug("???") == "untitled"


def test_write_extraction_pages_creates_entity_concept_and_suggested_pages(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)

    result = write_extraction_pages(_extraction(), wiki_path=wiki_path)

    assert result.created_count == 4
    assert result.updated_count == 0
    assert wiki_path.joinpath("entities", "memoweaver.md").exists()
    assert wiki_path.joinpath("concepts", "llm-native-wiki.md").exists()
    assert wiki_path.joinpath("concepts", "knowledge-weaving.md").exists()
    assert wiki_path.joinpath("concepts", "memoweaver-architecture.md").exists()

    entity_text = wiki_path.joinpath("entities", "memoweaver.md").read_text(encoding="utf-8")
    assert "# MemoWeaver" in entity_text
    assert "type: entity" in entity_text
    assert "source_ids:" in entity_text
    assert "src_demo" in entity_text
    assert "Headless LLM wiki maintainer" in entity_text
    assert "Parser output feeds extraction" in entity_text


def test_write_extraction_pages_is_idempotent_and_preserves_manual_notes(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    first = write_extraction_pages(_extraction(), wiki_path=wiki_path)
    entity_path = wiki_path / "entities" / "memoweaver.md"
    entity_path.write_text(entity_path.read_text(encoding="utf-8") + "\n## Manual Notes\n\nKeep this human note.\n", encoding="utf-8")

    second = write_extraction_pages(_extraction(), wiki_path=wiki_path)

    text = entity_path.read_text(encoding="utf-8")
    assert first.created_count == 4
    assert second.created_count == 0
    assert second.updated_count == 4
    assert text.count("<!-- memoweaver:generated:start -->") == 1
    assert "Keep this human note." in text


def test_write_pages_cli_reads_extraction_json_and_outputs_summary(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    extraction_path = tmp_path / "extraction.json"
    init_wiki(wiki_path)
    extraction_path.write_text(json.dumps(_extraction().to_dict(), ensure_ascii=False), encoding="utf-8")

    result = CliRunner().invoke(cli, ["write-pages", str(extraction_path), "--wiki", str(wiki_path)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["created_count"] == 4
    assert payload["updated_count"] == 0
    assert "entities/memoweaver.md" in payload["written_pages"]
    assert wiki_path.joinpath("entities", "memoweaver.md").exists()
