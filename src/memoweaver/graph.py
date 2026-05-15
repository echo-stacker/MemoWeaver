from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTENT_DIRECTORIES = ("entities", "concepts", "comparisons", "queries")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass(frozen=True)
class WikiPageNode:
    """One Markdown page in a MemoWeaver wiki graph."""

    path: Path
    wiki_path: Path
    title: str
    aliases: tuple[str, ...] = ()

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.wiki_path).as_posix()

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "path": self.relative_path, "aliases": list(self.aliases)}


@dataclass(frozen=True)
class WikiGraph:
    """Resolved wikilink graph for a MemoWeaver wiki."""

    wiki_path: Path
    nodes: tuple[WikiPageNode, ...]
    outbound: dict[str, tuple[str, ...]]
    inbound: dict[str, tuple[str, ...]]
    unresolved: dict[str, tuple[str, ...]]

    def node_for_path(self, relative_path: str) -> WikiPageNode | None:
        return {node.relative_path: node for node in self.nodes}.get(relative_path)

    def outbound_paths(self, relative_path: str) -> list[str]:
        return list(self.outbound.get(relative_path, ()))

    def inbound_paths(self, relative_path: str) -> list[str]:
        return list(self.inbound.get(relative_path, ()))

    def neighbor_paths(self, relative_path: str) -> list[str]:
        seen: set[str] = set()
        neighbors: list[str] = []
        for path in (*self.outbound.get(relative_path, ()), *self.inbound.get(relative_path, ())):
            if path != relative_path and path not in seen:
                seen.add(path)
                neighbors.append(path)
        return neighbors

    def orphan_paths(self) -> list[str]:
        return [node.relative_path for node in self.nodes if not self.outbound.get(node.relative_path) and not self.inbound.get(node.relative_path)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "wiki_path": str(self.wiki_path),
            "nodes": [node.to_dict() for node in self.nodes],
            "outbound": {key: list(value) for key, value in self.outbound.items()},
            "inbound": {key: list(value) for key, value in self.inbound.items()},
            "unresolved": {key: list(value) for key, value in self.unresolved.items()},
        }


def parse_wikilinks(text: str) -> list[str]:
    """Extract normalized wikilink targets from Markdown text.

    Supports common Obsidian forms: ``[[Page]]``, ``[[Page#Section]]``,
    ``[[Page|Alias]]``, and path targets like ``[[concepts/Page]]``. The returned
    values are link targets only; aliases and heading fragments are stripped.
    """

    targets: list[str] = []
    for match in WIKILINK_PATTERN.finditer(text):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.append(target)
    return targets


def build_wiki_graph(wiki_path: str | Path) -> WikiGraph:
    """Build a resolved inbound/outbound graph from wiki Markdown files."""

    wiki = Path(wiki_path)
    nodes = tuple(WikiPageNode(path=path, wiki_path=wiki, title=_page_title(path), aliases=tuple(_page_aliases(path))) for path in _scan_pages(wiki))
    lookup = _build_lookup(nodes)
    outbound_sets: dict[str, set[str]] = {node.relative_path: set() for node in nodes}
    inbound_sets: dict[str, set[str]] = {node.relative_path: set() for node in nodes}
    unresolved: dict[str, list[str]] = {node.relative_path: [] for node in nodes}

    for node in nodes:
        text = node.path.read_text(encoding="utf-8")
        for target in parse_wikilinks(text):
            resolved = _resolve_target(target, lookup=lookup, wiki=wiki)
            if resolved is None:
                unresolved[node.relative_path].append(target)
                continue
            if resolved != node.relative_path:
                outbound_sets[node.relative_path].add(resolved)
                inbound_sets[resolved].add(node.relative_path)

    return WikiGraph(
        wiki_path=wiki,
        nodes=nodes,
        outbound={key: tuple(sorted(value)) for key, value in outbound_sets.items()},
        inbound={key: tuple(sorted(value)) for key, value in inbound_sets.items()},
        unresolved={key: tuple(values) for key, values in unresolved.items() if values},
    )


def expand_wiki_neighborhood(seed_pages: list[Path], *, graph: WikiGraph, depth: int = 1, limit: int = 10) -> list[Path]:
    """Return seed pages followed by linked neighbor pages up to ``depth`` hops."""

    if limit <= 0:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    frontier: list[str] = []
    for page in seed_pages:
        relative = page.relative_to(graph.wiki_path).as_posix() if page.is_absolute() or graph.wiki_path in page.parents else page.as_posix()
        if relative in graph.outbound and relative not in seen:
            seen.add(relative)
            ordered.append(relative)
            frontier.append(relative)
            if len(ordered) >= limit:
                return [graph.wiki_path / item for item in ordered]
    for _ in range(max(0, depth)):
        next_frontier: list[str] = []
        for relative in frontier:
            for neighbor in graph.neighbor_paths(relative):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                ordered.append(neighbor)
                next_frontier.append(neighbor)
                if len(ordered) >= limit:
                    return [graph.wiki_path / item for item in ordered]
        frontier = next_frontier
        if not frontier:
            break
    return [graph.wiki_path / item for item in ordered[:limit]]


def _scan_pages(wiki: Path) -> list[Path]:
    pages: list[Path] = []
    for directory in CONTENT_DIRECTORIES:
        root = wiki / directory
        if root.exists():
            pages.extend(path for path in sorted(root.rglob("*.md")) if path.is_file())
    return sorted(pages)


def _build_lookup(nodes: tuple[WikiPageNode, ...]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for node in nodes:
        candidates = [node.relative_path, node.relative_path.removesuffix(".md"), node.path.stem, node.path.stem.replace("-", " "), node.title, *node.aliases]
        for candidate in candidates:
            lookup.setdefault(_normalize_target(candidate), node.relative_path)
    return lookup


def _resolve_target(target: str, *, lookup: dict[str, str], wiki: Path) -> str | None:
    normalized = _normalize_target(target)
    if normalized in lookup:
        return lookup[normalized]
    path = Path(target)
    if any(str(path).startswith(f"{directory}/") for directory in CONTENT_DIRECTORIES):
        candidate = path if path.suffix == ".md" else path.with_suffix(".md")
        candidate_path = (wiki / candidate).as_posix()
        if Path(candidate_path).exists():
            return candidate.as_posix()
    return None


def _page_title(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(text)
    if title := frontmatter.get("title"):
        return title
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or path.stem
    return path.stem.replace("-", " ").title()


def _page_aliases(path: Path) -> list[str]:
    return _frontmatter_list_values(path.read_text(encoding="utf-8"), "aliases")


def _frontmatter(text: str) -> dict[str, str]:
    bounds = _frontmatter_bounds(text)
    if bounds is None:
        return {}
    start, end = bounds
    metadata: dict[str, str] = {}
    for line in text[start:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value:
            metadata[key.strip()] = value
    return metadata


def _frontmatter_list_values(text: str, key: str) -> list[str]:
    bounds = _frontmatter_bounds(text)
    if bounds is None:
        return []
    start, end = bounds
    values: list[str] = []
    collecting = False
    for line in text[start:end].splitlines():
        stripped = line.strip()
        if collecting:
            if stripped.startswith("-"):
                value = stripped[1:].strip()
                if value:
                    values.append(value)
                continue
            if line and not line.startswith((" ", "\t")):
                collecting = False
        if stripped == f"{key}:":
            collecting = True
    return values


def _frontmatter_bounds(text: str) -> tuple[int, int] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return 4, end


def _normalize_target(target: str) -> str:
    cleaned = target.strip().removesuffix(".md")
    return " ".join(cleaned.replace("-", " ").replace("_", " ").lower().split())
