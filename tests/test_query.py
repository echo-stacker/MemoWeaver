from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.llm import LLMProvider
from memoweaver.query import ask_wiki, search_wiki_pages
from memoweaver.wiki import init_wiki


class FakeProvider(LLMProvider):
    def __init__(self) -> None:
        self.system = ""
        self.user = ""

    def complete(self, *, system: str, user: str, max_tokens: int = 1600) -> str:
        self.system = system
        self.user = user
        return "MemoWeaver uses parser output and LLM extraction to create durable wiki pages.\n\nSources: [[concepts/llm-native-wiki|LLM-native wiki]], [[entities/memoweaver|MemoWeaver]]"


def _write_page(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\ntype: concept\n---\n# {title}\n\n{body}\n", encoding="utf-8")


def test_search_wiki_pages_ranks_keyword_matches_and_returns_snippets(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    init_wiki(wiki)
    _write_page(wiki / "concepts" / "llm-native-wiki.md", "LLM-native wiki", "MemoWeaver compiles raw notes into a maintained wiki before query time.")
    _write_page(wiki / "entities" / "memoweaver.md", "MemoWeaver", "Parser output feeds LLM extraction, then the writer creates pages.")
    _write_page(wiki / "concepts" / "unrelated.md", "Unrelated", "This page discusses gardening and recipes.")

    results = search_wiki_pages("How does MemoWeaver use LLM extraction?", wiki_path=wiki, limit=2)

    assert [result.title for result in results] == ["MemoWeaver", "LLM-native wiki"]
    assert results[0].relative_path == "entities/memoweaver.md"
    assert "LLM extraction" in results[0].snippet
    assert all("unrelated" not in result.relative_path for result in results)


def test_ask_wiki_builds_context_from_matching_pages_and_cites_sources(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    init_wiki(wiki)
    _write_page(wiki / "concepts" / "llm-native-wiki.md", "LLM-native wiki", "MemoWeaver compiles raw notes into a maintained wiki.")
    _write_page(wiki / "entities" / "memoweaver.md", "MemoWeaver", "Parser output feeds LLM extraction.")
    provider = FakeProvider()

    answer = ask_wiki("What does MemoWeaver do?", wiki_path=wiki, provider=provider, limit=3)

    assert answer.question == "What does MemoWeaver do?"
    assert "durable wiki pages" in answer.answer
    assert [source.title for source in answer.sources] == ["MemoWeaver", "LLM-native wiki"]
    assert "Parser output feeds LLM extraction" in provider.user
    assert "Answer only from the provided MemoWeaver wiki context" in provider.system


def test_cli_ask_outputs_answer_json_and_can_save_query_page(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    init_wiki(wiki)
    _write_page(wiki / "entities" / "memoweaver.md", "MemoWeaver", "MemoWeaver creates maintained Markdown wiki pages.")

    class CliFakeProvider(FakeProvider):
        def complete(self, *, system: str, user: str, max_tokens: int = 1600) -> str:
            return "MemoWeaver creates maintained Markdown wiki pages."

    monkeypatch.setattr("memoweaver.cli.CodexHTTPProvider.from_env", lambda: CliFakeProvider())

    result = CliRunner().invoke(cli, ["ask", "What does MemoWeaver create?", "--wiki", str(wiki), "--json", "--save"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["question"] == "What does MemoWeaver create?"
    assert payload["answer"] == "MemoWeaver creates maintained Markdown wiki pages."
    assert payload["sources"] == [{"title": "MemoWeaver", "path": "entities/memoweaver.md", "score": 1}]
    saved_pages = list((wiki / "queries").glob("*.md"))
    assert len(saved_pages) == 1
    saved_text = saved_pages[0].read_text(encoding="utf-8")
    assert "# What does MemoWeaver create?" in saved_text
    assert "[[entities/memoweaver|MemoWeaver]]" in saved_text
