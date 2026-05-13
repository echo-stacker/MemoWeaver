from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.llm import LLMExtraction
from memoweaver.resolver import resolve_extraction_pages, scan_wiki_pages
from memoweaver.wiki import init_wiki


def _extraction() -> LLMExtraction:
    return LLMExtraction(
        source_id="src_resolver",
        summary="Resolver decides whether extracted names should create or update pages.",
        entities=[{"name": "MemoWeaver", "type": "project"}],
        concepts=["LLM-native Wiki", "Knowledge Weaving"],
        claims=[],
        relations=[],
        suggested_pages=[{"title": "LLM-native Wiki", "reason": "duplicate suggested page"}],
    )


def test_scan_wiki_pages_builds_slug_title_and_alias_maps(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    page = wiki_path / "concepts" / "large-language-model-wiki.md"
    page.write_text(
        """---
title: Large Language Model Wiki
type: concept
aliases:
  - LLM-native Wiki
  - Agentic Knowledge Base
---
# Large Language Model Wiki
""",
        encoding="utf-8",
    )

    index = scan_wiki_pages(wiki_path)

    assert index.by_slug["concept:large-language-model-wiki"].path == page
    assert index.by_title["concept:large language model wiki"].path == page
    assert index.by_alias["concept:llm-native wiki"].path == page
    assert index.by_alias["concept:agentic knowledge base"].path == page


def test_resolve_extraction_pages_creates_updates_and_skips_duplicates(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    existing = wiki_path / "entities" / "memoweaver.md"
    existing.write_text("---\ntitle: MemoWeaver\ntype: entity\n---\n# MemoWeaver\n", encoding="utf-8")

    plan = resolve_extraction_pages(_extraction(), wiki_path=wiki_path)

    changes = {(change.page_type, change.title): change for change in plan.changes}
    assert changes[("entity", "MemoWeaver")].action == "update"
    assert changes[("entity", "MemoWeaver")].path == existing
    assert changes[("concept", "LLM-native Wiki")].action == "create"
    assert changes[("concept", "Knowledge Weaving")].action == "create"
    assert plan.create_count == 2
    assert plan.update_count == 1
    assert plan.skip_count == 1
    assert plan.skipped[0].title == "LLM-native Wiki"
    assert plan.skipped[0].reason == "duplicate target in extraction"


def test_resolve_extraction_pages_uses_aliases_for_updates(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    canonical = wiki_path / "concepts" / "large-language-model-wiki.md"
    canonical.write_text(
        "---\ntitle: Large Language Model Wiki\ntype: concept\naliases:\n  - LLM-native Wiki\n---\n# Large Language Model Wiki\n",
        encoding="utf-8",
    )

    plan = resolve_extraction_pages(_extraction(), wiki_path=wiki_path)
    llm_change = next(change for change in plan.changes if change.title == "LLM-native Wiki")

    assert llm_change.action == "update"
    assert llm_change.path == canonical
    assert llm_change.reason == "matched existing alias"


def test_resolve_pages_cli_outputs_dry_run_plan(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    extraction_path = tmp_path / "extraction.json"
    init_wiki(wiki_path)
    extraction_path.write_text(json.dumps(_extraction().to_dict(), ensure_ascii=False), encoding="utf-8")

    result = CliRunner().invoke(cli, ["resolve-pages", str(extraction_path), "--wiki", str(wiki_path)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["create_count"] == 3
    assert payload["update_count"] == 0
    assert payload["skip_count"] == 1
    assert payload["changes"][0]["action"] == "create"
    assert "concepts/llm-native-wiki.md" in [change["path"] for change in payload["changes"]]
