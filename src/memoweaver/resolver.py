from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from memoweaver.llm import LLMExtraction
from memoweaver.wiki_writer import page_slug

PageType = Literal["entity", "concept"]
ChangeAction = Literal["create", "update"]


@dataclass(frozen=True)
class WikiPageRef:
    """A discovered Markdown wiki page and the names that can resolve to it."""

    page_type: PageType
    title: str
    path: Path
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class WikiPageIndex:
    """Lookup tables used by the resolver.

    The index is intentionally derived from existing Markdown files rather than
    from a separate database. Early MemoWeaver wikis must remain inspectable and
    repairable with a text editor; a future state store can cache this structure
    once the page contract is stable.
    """

    by_slug: dict[str, WikiPageRef]
    by_title: dict[str, WikiPageRef]
    by_alias: dict[str, WikiPageRef]


@dataclass(frozen=True)
class WikiChange:
    """A dry-run decision for one extracted entity or concept."""

    action: ChangeAction
    page_type: PageType
    title: str
    path: Path
    reason: str

    def to_dict(self, wiki_path: Path) -> dict[str, Any]:
        return {
            "action": self.action,
            "page_type": self.page_type,
            "title": self.title,
            "path": str(self.path.relative_to(wiki_path)),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SkippedChange:
    """A candidate that resolver deliberately did not put into the write plan."""

    page_type: PageType
    title: str
    path: Path
    reason: str

    def to_dict(self, wiki_path: Path) -> dict[str, Any]:
        return {
            "page_type": self.page_type,
            "title": self.title,
            "path": str(self.path.relative_to(wiki_path)),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WikiChangePlan:
    """Create/update/skip plan for extraction output.

    The writer can already create pages directly. This plan is the layer that
    makes long-running wikis safer: callers can dry-run decisions, review the
    target paths, and later pass the plan into writer/index/log modules without
    re-resolving names differently.
    """

    wiki_path: Path
    changes: tuple[WikiChange, ...]
    skipped: tuple[SkippedChange, ...]

    @property
    def create_count(self) -> int:
        return sum(1 for change in self.changes if change.action == "create")

    @property
    def update_count(self) -> int:
        return sum(1 for change in self.changes if change.action == "update")

    @property
    def skip_count(self) -> int:
        return len(self.skipped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wiki_path": str(self.wiki_path),
            "create_count": self.create_count,
            "update_count": self.update_count,
            "skip_count": self.skip_count,
            "changes": [change.to_dict(self.wiki_path) for change in self.changes],
            "skipped": [change.to_dict(self.wiki_path) for change in self.skipped],
        }


def scan_wiki_pages(wiki_path: str | Path) -> WikiPageIndex:
    """Scan existing entity/concept Markdown pages into resolver lookup maps."""

    wiki = Path(wiki_path)
    by_slug: dict[str, WikiPageRef] = {}
    by_title: dict[str, WikiPageRef] = {}
    by_alias: dict[str, WikiPageRef] = {}
    for page_type, directory in (("entity", "entities"), ("concept", "concepts")):
        for path in sorted((wiki / directory).glob("*.md")):
            metadata = _read_frontmatter(path)
            title = metadata.get("title") or _title_from_heading_or_stem(path)
            aliases = tuple(metadata.get("aliases", []))
            reference = WikiPageRef(page_type=page_type, title=title, path=path, aliases=aliases)
            by_slug[_key(page_type, path.stem)] = reference
            by_title[_key(page_type, _normalize(title))] = reference
            for alias in aliases:
                by_alias[_key(page_type, _normalize(alias))] = reference
    return WikiPageIndex(by_slug=by_slug, by_title=by_title, by_alias=by_alias)


def resolve_extraction_pages(extraction: LLMExtraction, *, wiki_path: str | Path) -> WikiChangePlan:
    """Resolve extracted names into a dry-run page change plan.

    The MVP decision order is deliberately boring and explainable:
    1. slug match, because existing writer-created filenames are the most common;
    2. title match from frontmatter/heading;
    3. alias match from frontmatter `aliases`;
    4. create a new page when no existing page matches.

    It also suppresses duplicate targets inside a single extraction payload so a
    concept that appears both as an extracted concept and as a suggested page does
    not get written twice in the same run.
    """

    wiki = Path(wiki_path)
    index = scan_wiki_pages(wiki)
    changes: list[WikiChange] = []
    skipped: list[SkippedChange] = []
    seen_targets: set[str] = set()

    for page_type, title in _candidates(extraction):
        target = _resolve_one(index, wiki, page_type, title)
        unique_target = _key(page_type, str(target.path.relative_to(wiki)))
        if unique_target in seen_targets:
            skipped.append(SkippedChange(page_type=page_type, title=title, path=target.path, reason="duplicate target in extraction"))
            continue
        seen_targets.add(unique_target)
        changes.append(target)

    return WikiChangePlan(wiki_path=wiki, changes=tuple(changes), skipped=tuple(skipped))


def _candidates(extraction: LLMExtraction) -> list[tuple[PageType, str]]:
    candidates: list[tuple[PageType, str]] = []
    for entity in extraction.entities:
        title = str(entity.get("name") or "").strip()
        if title:
            candidates.append(("entity", title))
    for concept in extraction.concepts:
        title = str(concept).strip()
        if title:
            candidates.append(("concept", title))
    for page in extraction.suggested_pages:
        title = str(page.get("title") or "").strip()
        if title:
            candidates.append(("concept", title))
    return candidates


def _resolve_one(index: WikiPageIndex, wiki: Path, page_type: PageType, title: str) -> WikiChange:
    slug = page_slug(title)
    slug_key = _key(page_type, slug)
    if slug_key in index.by_slug:
        return _update(title, index.by_slug[slug_key], "matched existing slug")

    title_key = _key(page_type, _normalize(title))
    if title_key in index.by_title:
        return _update(title, index.by_title[title_key], "matched existing title")
    if title_key in index.by_alias:
        return _update(title, index.by_alias[title_key], "matched existing alias")

    directory = "entities" if page_type == "entity" else "concepts"
    return WikiChange(action="create", page_type=page_type, title=title, path=wiki / directory / f"{slug}.md", reason="no existing page matched")


def _update(title: str, reference: WikiPageRef, reason: str) -> WikiChange:
    return WikiChange(action="update", page_type=reference.page_type, title=title, path=reference.path, reason=reason)


def _read_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    lines = text[4:end].splitlines()
    metadata: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if current_list_key and stripped.startswith("-"):
            metadata.setdefault(current_list_key, []).append(stripped[1:].strip())
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            metadata[key] = value
        else:
            metadata[key] = []
            current_list_key = key
    return metadata


def _title_from_heading_or_stem(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _key(page_type: str, value: str) -> str:
    return f"{page_type}:{value}"
