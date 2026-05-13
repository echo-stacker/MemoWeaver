from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memoweaver.llm import LLMExtraction

GENERATED_START = "<!-- memoweaver:generated:start -->"
GENERATED_END = "<!-- memoweaver:generated:end -->"


@dataclass(frozen=True)
class WrittenPage:
    """A single Markdown page written by the wiki writer."""

    path: Path
    created: bool


@dataclass(frozen=True)
class WikiWriteResult:
    """Summary returned after materializing extraction output into wiki pages."""

    wiki_path: Path
    pages: tuple[WrittenPage, ...]

    @property
    def created_count(self) -> int:
        return sum(1 for page in self.pages if page.created)

    @property
    def updated_count(self) -> int:
        return sum(1 for page in self.pages if not page.created)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wiki_path": str(self.wiki_path),
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "written_pages": [str(page.path.relative_to(self.wiki_path)) for page in self.pages],
        }


def page_slug(title: str) -> str:
    """Return a stable ASCII slug for early wiki filenames.

    The MVP deliberately uses a conservative slugger instead of transliteration or
    locale-specific rules. That keeps filenames portable and deterministic while
    leaving a clear seam for a future resolver that can handle aliases, Unicode
    titles, and collision policies.
    """

    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower())
    slug = slug.strip("-")
    return slug or "untitled"


def write_extraction_pages(extraction: LLMExtraction, *, wiki_path: str | Path) -> WikiWriteResult:
    """Create/update Markdown entity and concept pages from LLM extraction.

    This module is intentionally a writer, not a resolver. It does not merge
    aliases, choose canonical names, or modify indexes/backlinks yet. Its job is
    to give the project the first durable end-to-end artifact: structured LLM
    output becomes real Markdown files with a generated section that can be
    refreshed while preserving human edits outside the section.
    """

    wiki = Path(wiki_path)
    pages: list[WrittenPage] = []

    for entity in extraction.entities:
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        pages.append(_write_page(wiki / "entities" / f"{page_slug(name)}.md", _entity_page(name, entity, extraction)))

    for concept in extraction.concepts:
        title = str(concept).strip()
        if not title:
            continue
        pages.append(_write_page(wiki / "concepts" / f"{page_slug(title)}.md", _concept_page(title, extraction, reason="extracted concept")))

    for page in extraction.suggested_pages:
        title = str(page.get("title") or "").strip()
        if not title:
            continue
        reason = str(page.get("reason") or "suggested by LLM").strip()
        pages.append(_write_page(wiki / "concepts" / f"{page_slug(title)}.md", _concept_page(title, extraction, reason=reason)))

    return WikiWriteResult(wiki_path=wiki, pages=tuple(pages))


def extraction_from_dict(payload: dict[str, Any]) -> LLMExtraction:
    """Rehydrate an `LLMExtraction` from JSON produced by `LLMExtraction.to_dict()`.

    The CLI uses this to bridge the current gap between the LLM module and the
    writer module. Later, when extraction results are cached in wiki state, this
    helper remains useful for migrations and fixture-based tests.
    """

    return LLMExtraction(
        source_id=str(payload.get("source_id") or ""),
        summary=str(payload.get("summary") or ""),
        entities=_dict_list(payload.get("entities")),
        concepts=[str(item) for item in payload.get("concepts") or [] if str(item).strip()],
        claims=_dict_list(payload.get("claims")),
        relations=_dict_list(payload.get("relations")),
        suggested_pages=_dict_list(payload.get("suggested_pages")),
        raw_response=payload.get("raw_response") if isinstance(payload.get("raw_response"), dict) else {},
    )


def _write_page(path: Path, generated_body: str) -> WrittenPage:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    if created:
        path.write_text(generated_body + "\n", encoding="utf-8")
    else:
        existing = path.read_text(encoding="utf-8")
        path.write_text(_replace_generated_section(existing, generated_body) + "\n", encoding="utf-8")
    return WrittenPage(path=path, created=created)


def _replace_generated_section(existing: str, generated_body: str) -> str:
    start = existing.find(GENERATED_START)
    end = existing.find(GENERATED_END)
    if start >= 0 and end > start:
        tail_start = end + len(GENERATED_END)
        return existing[:start].rstrip() + "\n\n" + generated_body.rstrip() + existing[tail_start:].rstrip()
    return existing.rstrip() + "\n\n" + generated_body.rstrip()


def _entity_page(name: str, entity: dict[str, Any], extraction: LLMExtraction) -> str:
    entity_type = str(entity.get("type") or "entity").strip()
    description = str(entity.get("description") or "").strip()
    body = [
        _frontmatter(title=name, page_type="entity", source_id=extraction.source_id),
        f"# {name}",
        GENERATED_START,
        f"Source: `{extraction.source_id}`",
        "",
        f"Type: {entity_type}",
    ]
    if description:
        body.extend(["", "## Description", "", description])
    body.extend(_knowledge_sections(extraction))
    body.append(GENERATED_END)
    return "\n".join(body)


def _concept_page(title: str, extraction: LLMExtraction, *, reason: str) -> str:
    body = [
        _frontmatter(title=title, page_type="concept", source_id=extraction.source_id),
        f"# {title}",
        GENERATED_START,
        f"Source: `{extraction.source_id}`",
        "",
        "## Why this page exists",
        "",
        reason,
    ]
    if extraction.summary:
        body.extend(["", "## Source Summary", "", extraction.summary])
    body.extend(_knowledge_sections(extraction))
    body.append(GENERATED_END)
    return "\n".join(body)


def _frontmatter(*, title: str, page_type: str, source_id: str) -> str:
    # Keep frontmatter intentionally tiny. YAML dependencies are unnecessary for
    # this first slice, and the generated values are plain strings controlled by
    # MemoWeaver rather than arbitrary nested data.
    return f"---\ntitle: {title}\ntype: {page_type}\nsource_ids:\n  - {source_id}\n---"


def _knowledge_sections(extraction: LLMExtraction) -> list[str]:
    sections: list[str] = []
    if extraction.summary:
        sections.extend(["", "## Summary", "", extraction.summary])
    if extraction.claims:
        sections.extend(["", "## Claims", ""])
        sections.extend(f"- {claim.get('text', '')}" for claim in extraction.claims if claim.get("text"))
    if extraction.relations:
        sections.extend(["", "## Relations", ""])
        for relation in extraction.relations:
            source = relation.get("source", "")
            target = relation.get("target", "")
            kind = relation.get("type", "relates_to")
            if source or target:
                sections.append(f"- {source} — {kind} — {target}")
    return sections


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
