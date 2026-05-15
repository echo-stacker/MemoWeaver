from __future__ import annotations

from pathlib import Path

from memoweaver.graph import build_wiki_graph, expand_wiki_neighborhood, parse_wikilinks
from memoweaver.llm import LLMProvider
from memoweaver.query import ask_wiki
from memoweaver.wiki import init_wiki


def _write_page(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\ntype: concept\n---\n# {title}\n\n{body}\n", encoding="utf-8")


class CapturingProvider(LLMProvider):
    def __init__(self) -> None:
        self.user = ""

    def complete(self, *, system: str, user: str, max_tokens: int = 1600) -> str:
        self.user = user
        return "Answer grounded in graph-expanded context."


def test_parse_wikilinks_normalizes_aliases_headings_and_paths() -> None:
    links = parse_wikilinks("See [[MemoWeaver|the project]], [[concepts/Query#MVP]], and [[Graph]].")

    assert links == ["MemoWeaver", "concepts/Query", "Graph"]


def test_build_wiki_graph_resolves_outbound_and_inbound_links(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    init_wiki(wiki)
    _write_page(wiki / "entities" / "memoweaver.md", "MemoWeaver", "MemoWeaver uses [[LLM-native wiki]] and [[concepts/query]].")
    _write_page(wiki / "concepts" / "llm-native-wiki.md", "LLM-native wiki", "A durable compiled wiki.")
    _write_page(wiki / "concepts" / "query.md", "Query", "Questions use wiki context.")
    _write_page(wiki / "concepts" / "orphan.md", "Orphan", "No links here.")

    graph = build_wiki_graph(wiki)

    assert graph.outbound_paths("entities/memoweaver.md") == ["concepts/llm-native-wiki.md", "concepts/query.md"]
    assert graph.inbound_paths("concepts/query.md") == ["entities/memoweaver.md"]
    assert graph.neighbor_paths("entities/memoweaver.md") == ["concepts/llm-native-wiki.md", "concepts/query.md"]
    assert graph.orphan_paths() == ["concepts/orphan.md"]


def test_expand_wiki_neighborhood_adds_linked_pages_after_seed_pages(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    init_wiki(wiki)
    _write_page(wiki / "entities" / "memoweaver.md", "MemoWeaver", "MemoWeaver links to [[LLM-native wiki]].")
    _write_page(wiki / "concepts" / "llm-native-wiki.md", "LLM-native wiki", "Graph expansion should include this neighbor.")

    graph = build_wiki_graph(wiki)
    expanded = expand_wiki_neighborhood([wiki / "entities" / "memoweaver.md"], graph=graph, depth=1, limit=5)

    assert [path.relative_to(wiki).as_posix() for path in expanded] == [
        "entities/memoweaver.md",
        "concepts/llm-native-wiki.md",
    ]


def test_ask_wiki_includes_graph_neighbor_context(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    init_wiki(wiki)
    _write_page(wiki / "entities" / "memoweaver.md", "MemoWeaver", "MemoWeaver links to [[LLM-native wiki]].")
    _write_page(wiki / "concepts" / "llm-native-wiki.md", "LLM-native wiki", "This neighbor page explains compiled knowledge before query time.")
    provider = CapturingProvider()

    answer = ask_wiki("What does MemoWeaver link to?", wiki_path=wiki, provider=provider, limit=1, graph_depth=1)

    assert answer.answer == "Answer grounded in graph-expanded context."
    assert [source.relative_path for source in answer.sources] == ["entities/memoweaver.md", "concepts/llm-native-wiki.md"]
    assert "This neighbor page explains compiled knowledge" in provider.user
