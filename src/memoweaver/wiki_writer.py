from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memoweaver.llm import LLMExtraction

if TYPE_CHECKING:
    from memoweaver.resolver import WikiChangePlan

GENERATED_START = "<!-- memoweaver:generated:start -->"
GENERATED_END = "<!-- memoweaver:generated:end -->"
INDEX_START = "<!-- memoweaver:index:start -->"
INDEX_END = "<!-- memoweaver:index:end -->"


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


def write_extraction_pages(extraction: LLMExtraction, *, wiki_path: str | Path, plan: "WikiChangePlan | None" = None) -> WikiWriteResult:
    """Create/update Markdown entity and concept pages from LLM extraction.

    Without a plan, the writer keeps its original slug-based behavior for simple
    one-shot use. When a `WikiChangePlan` is supplied, path decisions come from
    the resolver instead. That separation matters for long-lived wikis: resolver
    owns canonical naming and alias matching; writer owns safe generated-section
    replacement and preservation of human notes.
    """

    wiki = Path(wiki_path)
    if plan is not None:
        result = _write_planned_pages(extraction, wiki=wiki, plan=plan)
        _maintain_index(wiki)
        _append_write_log(wiki, extraction=extraction, result=result, skipped=plan.skipped)
        return result

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

    result = WikiWriteResult(wiki_path=wiki, pages=tuple(pages))
    _maintain_index(wiki)
    _append_write_log(wiki, extraction=extraction, result=result, skipped=())
    return result


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


def _write_planned_pages(extraction: LLMExtraction, *, wiki: Path, plan: "WikiChangePlan") -> WikiWriteResult:
    entities = {str(entity.get("name") or "").strip(): entity for entity in extraction.entities if str(entity.get("name") or "").strip()}
    concept_reasons = {str(concept).strip(): "extracted concept" for concept in extraction.concepts if str(concept).strip()}
    for page in extraction.suggested_pages:
        title = str(page.get("title") or "").strip()
        if title and title not in concept_reasons:
            concept_reasons[title] = str(page.get("reason") or "suggested by LLM").strip()

    pages: list[WrittenPage] = []
    for change in plan.changes:
        if change.page_type == "entity":
            entity = entities.get(change.title, {"name": change.title})
            display_title = _existing_page_title(change.path, fallback=change.title) if change.action == "update" else change.title
            body = _entity_page(display_title, entity, extraction)
        else:
            display_title = _existing_page_title(change.path, fallback=change.title) if change.action == "update" else change.title
            body = _concept_page(display_title, extraction, reason=concept_reasons.get(change.title, "resolved from extraction"))
        pages.append(_write_page(change.path, body))
    return WikiWriteResult(wiki_path=wiki, pages=tuple(pages))


def _write_page(path: Path, generated_body: str) -> WrittenPage:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    if created:
        path.write_text(generated_body + "\n", encoding="utf-8")
    else:
        existing = path.read_text(encoding="utf-8")
        updated = _replace_generated_section(existing, generated_body)
        updated = _merge_frontmatter_source_ids(updated, generated_body)
        path.write_text(updated + "\n", encoding="utf-8")
    return WrittenPage(path=path, created=created)


def _replace_generated_section(existing: str, generated_body: str) -> str:
    generated_section = _generated_section(generated_body)
    start = existing.find(GENERATED_START)
    end = existing.find(GENERATED_END)
    if start >= 0 and end > start:
        tail_start = end + len(GENERATED_END)
        return existing[:start].rstrip() + "\n" + generated_section.rstrip() + existing[tail_start:].rstrip()
    return existing.rstrip() + "\n\n" + generated_section.rstrip()


def _merge_frontmatter_source_ids(existing_text: str, generated_body: str) -> str:
    """Merge the new extraction source id into existing page frontmatter.

    Updates must preserve provenance from earlier sources. Because the writer
    replaces only the generated body for existing pages, the existing
    frontmatter remains authoritative for user-curated fields such as aliases;
    this helper performs the one metadata mutation MemoWeaver owns: append the
    latest generated ``source_ids`` without duplicating previous entries.
    """

    existing_bounds = _frontmatter_bounds(existing_text)
    generated_bounds = _frontmatter_bounds(generated_body)
    if existing_bounds is None or generated_bounds is None:
        return existing_text

    existing_start, existing_end = existing_bounds
    generated_start, generated_end = generated_bounds
    existing_frontmatter = existing_text[existing_start:existing_end]
    generated_frontmatter = generated_body[generated_start:generated_end]
    merged_ids = _dedupe_preserving_order(
        _frontmatter_list_values(existing_frontmatter, "source_ids")
        + _frontmatter_list_values(generated_frontmatter, "source_ids")
    )
    if not merged_ids:
        return existing_text
    merged_frontmatter = _replace_frontmatter_list(existing_frontmatter, "source_ids", merged_ids)
    return existing_text[:existing_start] + merged_frontmatter + existing_text[existing_end:]


def _frontmatter_bounds(text: str) -> tuple[int, int] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return 4, end


def _frontmatter_list_values(frontmatter: str, key: str) -> list[str]:
    values: list[str] = []
    lines = frontmatter.splitlines()
    collecting = False
    for line in lines:
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


def _replace_frontmatter_list(frontmatter: str, key: str, values: list[str]) -> str:
    replacement = [f"{key}:", *(f"  - {value}" for value in values)]
    lines = frontmatter.splitlines()
    output: list[str] = []
    index = 0
    replaced = False
    while index < len(lines):
        line = lines[index]
        if line.strip() == f"{key}:":
            output.extend(replacement)
            replaced = True
            index += 1
            while index < len(lines) and lines[index].strip().startswith("-"):
                index += 1
            continue
        output.append(line)
        index += 1
    if not replaced:
        output.extend(replacement)
    return "\n".join(output)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _generated_section(generated_body: str) -> str:
    start = generated_body.find(GENERATED_START)
    end = generated_body.find(GENERATED_END)
    if start >= 0 and end > start:
        return generated_body[start : end + len(GENERATED_END)]
    return generated_body


def _existing_page_title(path: Path, *, fallback: str) -> str:
    if not path.exists():
        return fallback
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if line.startswith("title:"):
                    return line.split(":", 1)[1].strip() or fallback
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


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


def _maintain_index(wiki: Path) -> None:
    """Refresh the generated page listing in ``index.md``.

    The index is derived from Markdown files on disk rather than from the latest
    write result only. That makes the command repair-friendly: rerunning
    ``write-pages`` can restore a missing generated index section and include
    pre-existing canonical pages targeted by the resolver.
    """

    index_path = wiki / "index.md"
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else "# MemoWeaver Wiki Index\n"
    section = _index_section(wiki)
    index_path.write_text(_replace_marked_section(existing, section, start=INDEX_START, end=INDEX_END) + "\n", encoding="utf-8")


def _index_section(wiki: Path) -> str:
    lines = [INDEX_START, "", "## Generated Pages", ""]
    for heading, directory in [("Entities", "entities"), ("Concepts", "concepts"), ("Comparisons", "comparisons"), ("Queries", "queries")]:
        pages = _page_links(wiki, directory)
        if not pages:
            continue
        lines.extend([f"### {heading}", ""])
        lines.extend(pages)
        lines.append("")
    lines.append(INDEX_END)
    return "\n".join(lines).rstrip()


def _page_links(wiki: Path, directory: str) -> list[str]:
    root = wiki / directory
    if not root.exists():
        return []
    links: list[tuple[str, str]] = []
    for path in sorted(root.glob("*.md")):
        title = _existing_page_title(path, fallback=path.stem)
        relative = path.relative_to(wiki).with_suffix("").as_posix()
        links.append((title.lower(), f"- [[{relative}|{title}]]"))
    return [line for _, line in sorted(links)]


def _append_write_log(wiki: Path, *, extraction: LLMExtraction, result: WikiWriteResult, skipped: tuple[Any, ...]) -> None:
    log_path = wiki / "log.md"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# MemoWeaver Maintenance Log\n"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"- {timestamp} — Wiki pages written from `{extraction.source_id}`: {result.created_count} created, {result.updated_count} updated.",
    ]
    for page in result.pages:
        action = "created" if page.created else "updated"
        lines.append(f"  - {action} `{page.path.relative_to(wiki).as_posix()}`")
    for change in skipped:
        lines.append(f"  - skipped {change.reason} `{change.path.relative_to(wiki).as_posix()}`")
    log_path.write_text(existing.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _replace_marked_section(existing: str, new_section: str, *, start: str, end: str) -> str:
    start_index = existing.find(start)
    end_index = existing.find(end)
    if start_index >= 0 and end_index > start_index:
        tail_start = end_index + len(end)
        return existing[:start_index].rstrip() + "\n\n" + new_section.rstrip() + existing[tail_start:].rstrip()
    return existing.rstrip() + "\n\n" + new_section.rstrip()
