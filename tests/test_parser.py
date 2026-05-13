from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.ingest import ingest_file
from memoweaver.parser import parse_file, parse_markdown_text, parse_wiki_raw_source
from memoweaver.wiki import init_wiki


def test_parse_markdown_extracts_title_headings_paragraphs_code_and_chunks() -> None:
    markdown = """# Project Alpha

Intro paragraph about the project.

## Goals

- Make source material durable.
- Keep parser output predictable.

```python
print("hello")
```

## Notes

Final paragraph.
"""

    document = parse_markdown_text(markdown, source_id="src_test", source_path=Path("raw/articles/src_test.md"))

    assert document.title == "Project Alpha"
    assert [heading.text for heading in document.headings] == ["Project Alpha", "Goals", "Notes"]
    assert [heading.level for heading in document.headings] == [1, 2, 2]
    assert [block.kind for block in document.blocks] == ["heading", "paragraph", "heading", "paragraph", "code", "heading", "paragraph"]
    assert document.blocks[4].metadata["language"] == "python"
    assert "print(\"hello\")" in document.blocks[4].text
    assert len(document.chunks) >= 3
    assert document.chunks[0].source_id == "src_test"
    assert document.chunks[0].text.startswith("# Project Alpha")


def test_parse_plain_text_uses_first_non_empty_line_as_title_and_paragraph_chunks(tmp_path: Path) -> None:
    source_path = tmp_path / "note.txt"
    source_path.write_text("\nPlain text title\n\nFirst paragraph.\n\nSecond paragraph.\n", encoding="utf-8")

    document = parse_file(source_path, source_id="src_txt")

    assert document.title == "Plain text title"
    assert document.headings == []
    assert [block.kind for block in document.blocks] == ["paragraph", "paragraph", "paragraph"]
    assert [chunk.text for chunk in document.chunks] == ["Plain text title", "First paragraph.", "Second paragraph."]


def test_parse_wiki_raw_source_reads_ingest_metadata(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# Metadata Title\n\nBody text.\n", encoding="utf-8")
    init_wiki(wiki_path)
    ingest = ingest_file(source_path, wiki_path=wiki_path, title="Metadata Title")

    document = parse_wiki_raw_source(ingest.raw_path)

    assert document.source_id == ingest.record.source_id
    assert document.title == "Metadata Title"
    assert document.source_path == ingest.raw_path
    assert document.metadata["sha256"] == ingest.record.sha256
    assert document.metadata["original_path"].endswith("note.md")


def test_parsed_document_can_be_serialized_for_llm_stage(tmp_path: Path) -> None:
    source_path = tmp_path / "note.md"
    source_path.write_text("# Serializable\n\nA paragraph for JSON output.\n", encoding="utf-8")

    document = parse_file(source_path, source_id="src_json")
    payload = document.to_dict()

    assert payload["schema_version"] == 1
    assert payload["source_id"] == "src_json"
    assert payload["title"] == "Serializable"
    assert payload["blocks"][0]["kind"] == "heading"
    assert payload["chunks"][0]["source_id"] == "src_json"
    json.dumps(payload)


def test_cli_parse_outputs_json_summary_for_raw_source(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# CLI Parse\n\nA paragraph.\n", encoding="utf-8")
    init_wiki(wiki_path)
    ingest = ingest_file(source_path, wiki_path=wiki_path, title="CLI Parse")
    runner = CliRunner()

    result = runner.invoke(cli, ["parse", str(ingest.raw_path)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["source_id"] == ingest.record.source_id
    assert payload["title"] == "CLI Parse"
    assert payload["block_count"] == 2
    assert payload["chunk_count"] == 2
