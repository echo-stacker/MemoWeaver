from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memoweaver.graph import build_wiki_graph, expand_wiki_neighborhood
from memoweaver.llm import CodexHTTPProvider, LLMProvider
from memoweaver.wiki_writer import page_slug

CONTENT_DIRS = ("entities", "concepts", "comparisons", "queries")


@dataclass(frozen=True)
class WikiSearchResult:
    """A wiki page selected as context for a query."""

    title: str
    path: Path
    wiki_path: Path
    score: int
    snippet: str

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.wiki_path).as_posix()

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "path": self.relative_path, "score": self.score}


@dataclass(frozen=True)
class WikiAnswer:
    """Answer generated from a maintained MemoWeaver wiki."""

    question: str
    answer: str
    sources: tuple[WikiSearchResult, ...]
    saved_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question": self.question,
            "answer": self.answer,
            "sources": [source.to_dict() for source in self.sources],
        }
        if self.saved_path is not None:
            payload["saved_path"] = str(self.saved_path)
        return payload


def search_wiki_pages(query: str, *, wiki_path: str | Path, limit: int = 5) -> list[WikiSearchResult]:
    """Return wiki pages whose title/body match query terms, ranked by simple lexical score.

    This first query slice intentionally uses deterministic local lexical search
    instead of a vector database. It keeps MemoWeaver local-first and testable,
    while giving the future graph/vector layers a small public API to replace or
    augment.
    """

    wiki = Path(wiki_path)
    terms = _query_terms(query)
    if not terms:
        return []
    results: list[WikiSearchResult] = []
    for path in _iter_content_pages(wiki):
        text = path.read_text(encoding="utf-8")
        title = _page_title(text, fallback=path.stem)
        score = _score_page(title, text, terms)
        if score <= 0:
            continue
        results.append(WikiSearchResult(title=title, path=path, wiki_path=wiki, score=score, snippet=_snippet(text, terms)))
    results.sort(key=lambda result: (-result.score, -_title_match_count(result.title, terms), result.title.lower(), result.relative_path))
    return results[: max(0, limit)]


def ask_wiki(
    question: str,
    *,
    wiki_path: str | Path,
    provider: LLMProvider | None = None,
    limit: int = 5,
    save: bool = False,
    graph_depth: int = 1,
) -> WikiAnswer:
    """Answer a question using matching wiki pages as grounded context."""

    wiki = Path(wiki_path)
    seed_sources = search_wiki_pages(question, wiki_path=wiki, limit=limit)
    sources = tuple(_expand_search_results(seed_sources, wiki=wiki, depth=graph_depth, limit=limit))
    provider = provider or CodexHTTPProvider.from_env()
    system = (
        "Answer only from the provided MemoWeaver wiki context. "
        "If the context is insufficient, say what is missing. "
        "Cite source pages using their provided wikilinks."
    )
    user = _answer_prompt(question, sources)
    answer_text = provider.complete(system=system, user=user, max_tokens=1200).strip()
    saved_path = _save_query_page(wiki, question=question, answer=answer_text, sources=sources) if save else None
    return WikiAnswer(question=question, answer=answer_text, sources=sources, saved_path=saved_path)


def _expand_search_results(seed_sources: list[WikiSearchResult], *, wiki: Path, depth: int, limit: int) -> list[WikiSearchResult]:
    if not seed_sources or depth <= 0:
        return seed_sources[: max(0, limit)]
    graph = build_wiki_graph(wiki)
    expanded_paths = expand_wiki_neighborhood([source.path for source in seed_sources], graph=graph, depth=depth, limit=max(0, limit * (depth + 1)))
    by_path = {source.path: source for source in seed_sources}
    expanded: list[WikiSearchResult] = []
    for path in expanded_paths:
        if path in by_path:
            expanded.append(by_path[path])
            continue
        text = path.read_text(encoding="utf-8")
        expanded.append(WikiSearchResult(title=_page_title(text, fallback=path.stem), path=path, wiki_path=wiki, score=0, snippet=_snippet(text, [])))
    return expanded


def _iter_content_pages(wiki: Path) -> list[Path]:
    pages: list[Path] = []
    for directory in CONTENT_DIRS:
        root = wiki / directory
        if root.exists():
            pages.extend(sorted(root.glob("*.md")))
    return pages


def _query_terms(query: str) -> list[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "does",
        "from",
        "how",
        "is",
        "of",
        "the",
        "to",
        "use",
        "what",
        "with",
    }
    terms = []
    seen: set[str] = set()
    for term in re.findall(r"[A-Za-z0-9_\-]+", query.lower()):
        normalized = term.strip("-_")
        if len(normalized) < 2 or normalized in stopwords or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return terms


def _score_page(title: str, text: str, terms: list[str]) -> int:
    haystack_terms = set(re.findall(r"[A-Za-z0-9_\-]+", f"{title}\n{text}".lower()))
    return sum(1 for term in terms if term in haystack_terms)


def _title_match_count(title: str, terms: list[str]) -> int:
    title_terms = set(re.findall(r"[A-Za-z0-9_\-]+", title.lower()))
    return sum(1 for term in terms if term in title_terms)


def _page_title(text: str, *, fallback: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if line.startswith("title:"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return value
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _snippet(text: str, terms: list[str], *, max_chars: int = 240) -> str:
    clean = _strip_frontmatter(text)
    lines = [line.strip() for line in clean.splitlines() if line.strip() and not line.startswith("#")]
    for line in lines:
        lower = line.lower()
        if any(term in lower for term in terms):
            return line[:max_chars]
    return (lines[0] if lines else "")[:max_chars]


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4 :].lstrip()
    return text


def _answer_prompt(question: str, sources: tuple[WikiSearchResult, ...]) -> str:
    context_blocks = []
    for index, source in enumerate(sources, start=1):
        text = source.path.read_text(encoding="utf-8")
        context_blocks.append(
            "\n".join(
                [
                    f"[Source {index}] [[{source.relative_path.removesuffix('.md')}|{source.title}]]",
                    f"Path: {source.relative_path}",
                    _strip_frontmatter(text).strip()[:3000],
                ]
            )
        )
    context = "\n\n---\n\n".join(context_blocks) if context_blocks else "No matching wiki pages were found."
    return f"Question: {question}\n\nWiki context:\n{context}\n\nAnswer with concise Markdown and cite relevant source wikilinks."


def _save_query_page(wiki: Path, *, question: str, answer: str, sources: tuple[WikiSearchResult, ...]) -> Path:
    queries_dir = wiki / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)
    slug = page_slug(question)[:80] or "query"
    path = queries_dir / f"{slug}.md"
    if path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        path = queries_dir / f"{slug}-{timestamp}.md"
    source_lines = [f"- [[{source.relative_path.removesuffix('.md')}|{source.title}]]" for source in sources]
    body = [
        "---",
        f"title: {question}",
        "type: query",
        f"created_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "---",
        f"# {question}",
        "",
        "## Answer",
        "",
        answer,
        "",
        "## Sources",
        "",
        *(source_lines or ["- No matching source pages found."]),
    ]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path
