from __future__ import annotations

from pathlib import Path

from memoweaver.llm import LLMExtraction
from memoweaver.resolver import resolve_extraction_pages
from memoweaver.wiki import init_wiki
from memoweaver.wiki_writer import write_extraction_pages


def _extraction(source_id: str = "src_demo") -> LLMExtraction:
    return LLMExtraction(
        source_id=source_id,
        summary="MemoWeaver turns raw notes into maintained wiki pages.",
        entities=[{"name": "MemoWeaver", "type": "project", "description": "Headless LLM wiki maintainer"}],
        concepts=["LLM-native wiki"],
        claims=[],
        relations=[],
        suggested_pages=[],
    )


def test_write_extraction_pages_updates_index_with_created_pages_without_duplicates(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)

    write_extraction_pages(_extraction(), wiki_path=wiki_path)
    write_extraction_pages(_extraction(), wiki_path=wiki_path)

    index = wiki_path.joinpath("index.md").read_text(encoding="utf-8")
    assert "## Generated Pages" in index
    assert "### Entities" in index
    assert "- [[entities/memoweaver|MemoWeaver]]" in index
    assert "### Concepts" in index
    assert "- [[concepts/llm-native-wiki|LLM-native wiki]]" in index
    assert index.count("[[entities/memoweaver|MemoWeaver]]") == 1
    assert index.count("[[concepts/llm-native-wiki|LLM-native wiki]]") == 1


def test_write_extraction_pages_appends_maintenance_log_summary(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)

    write_extraction_pages(_extraction(), wiki_path=wiki_path)
    write_extraction_pages(_extraction("src_second"), wiki_path=wiki_path)

    log = wiki_path.joinpath("log.md").read_text(encoding="utf-8")
    assert "Wiki pages written from `src_demo`: 2 created, 0 updated" in log
    assert "Wiki pages written from `src_second`: 0 created, 2 updated" in log
    assert "created `entities/memoweaver.md`" in log
    assert "updated `entities/memoweaver.md`" in log


def test_write_extraction_pages_logs_resolver_skips(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    existing = wiki_path / "concepts" / "large-language-model-wiki.md"
    existing.write_text(
        "---\ntitle: Large Language Model Wiki\ntype: concept\naliases:\n  - LLM-native wiki\n---\n# Large Language Model Wiki\n",
        encoding="utf-8",
    )
    extraction = _extraction()
    extraction.suggested_pages.append({"title": "LLM-native wiki", "reason": "duplicate candidate"})
    plan = resolve_extraction_pages(extraction, wiki_path=wiki_path)

    write_extraction_pages(extraction, wiki_path=wiki_path, plan=plan)

    index = wiki_path.joinpath("index.md").read_text(encoding="utf-8")
    log = wiki_path.joinpath("log.md").read_text(encoding="utf-8")
    assert "- [[concepts/large-language-model-wiki|Large Language Model Wiki]]" in index
    assert "skipped duplicate target in extraction `concepts/large-language-model-wiki.md`" in log
