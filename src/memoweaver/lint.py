from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Severity = Literal["error", "warning"]

WIKILINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
CONTENT_DIRECTORIES = ("entities", "concepts", "comparisons", "queries")
INDEX_START = "<!-- memoweaver:index:start -->"
INDEX_END = "<!-- memoweaver:index:end -->"


@dataclass(frozen=True)
class LintIssue:
    """One machine-readable wiki health issue.

    Lint output is intended to serve both humans and future automation, so each
    issue carries a stable `code`, a severity, and a wiki-relative path. The
    message is descriptive text and should not be parsed by downstream tools.
    """

    code: str
    severity: Severity
    page_path: Path
    message: str

    @property
    def relative_path(self) -> str:
        parts = self.page_path.parts
        for directory in CONTENT_DIRECTORIES:
            if directory in parts:
                index = parts.index(directory)
                return str(Path(*parts[index:]))
        return str(self.page_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.relative_path,
            "message": self.message,
        }


@dataclass(frozen=True)
class LintReport:
    """Complete health report for a MemoWeaver wiki."""

    wiki_path: Path
    issues: tuple[LintIssue, ...]

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "wiki_path": str(self.wiki_path),
            "issue_count": self.issue_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def lint_wiki(wiki_path: str | Path) -> LintReport:
    """Run the first MemoWeaver wiki health checks.

    The MVP deliberately keeps lint file-based and dependency-free. It checks the
    Markdown artifacts that users can inspect and repair manually: missing
    frontmatter, broken `[[wikilinks]]`, and isolated pages. More expensive checks
    such as source drift, taxonomy consistency, and long-page warnings can build
    on this report shape later without changing CLI consumers.
    """

    wiki = Path(wiki_path)
    pages = _scan_pages(wiki)
    title_index = _build_title_index(pages)
    outbound: dict[Path, set[str]] = {page: set(_wikilinks(page.read_text(encoding="utf-8"))) for page in pages}
    inbound: dict[Path, set[Path]] = {page: set() for page in pages}
    issues: list[LintIssue] = []

    for page in pages:
        relative = page.relative_to(wiki)
        text = page.read_text(encoding="utf-8")
        if not _has_frontmatter(text):
            issues.append(
                LintIssue(
                    code="missing-frontmatter",
                    severity="warning",
                    page_path=page,
                    message="Page is missing frontmatter; resolver and future metadata checks may be less accurate.",
                )
            )
        for link_title in sorted(outbound[page]):
            target = title_index.get(_normalize_title(link_title))
            if target is None:
                issues.append(
                    LintIssue(
                        code="broken-wikilink",
                        severity="error",
                        page_path=page,
                        message=f"Wikilink [[{link_title}]] does not resolve to a known page title or filename.",
                    )
                )
            else:
                inbound[target].add(page)

    issues.extend(_duplicate_metadata_issues(pages))
    issues.extend(_index_completeness_issues(wiki, pages))

    # Treat "orphan" as an isolated content page, not merely a page with no
    # inbound links. This avoids flagging useful hub/index-style pages that link
    # outward and avoids noise for a one-page newborn wiki.
    if len(pages) > 1:
        for page in pages:
            if not inbound[page] and not outbound[page]:
                issues.append(
                    LintIssue(
                        code="orphan-page",
                        severity="warning",
                        page_path=page,
                        message="Page has no inbound or outbound wikilinks, so it is isolated from the wiki graph.",
                    )
                )

    return LintReport(wiki_path=wiki, issues=tuple(sorted(issues, key=lambda issue: (issue.relative_path, issue.code, issue.message))))


def _duplicate_metadata_issues(pages: list[Path]) -> list[LintIssue]:
    """Detect title and alias collisions between existing pages.

    Resolver relies on title/alias lookups to decide update targets. Reporting
    collisions here keeps the resolver simple: lint surfaces ambiguous metadata
    before an automated write accidentally updates the wrong canonical page.
    """

    issues: list[LintIssue] = []
    seen_titles: dict[str, tuple[str, Path]] = {}
    seen_aliases: dict[str, tuple[str, Path]] = {}
    for page in pages:
        text = page.read_text(encoding="utf-8")
        title = _primary_page_title(page, text)
        normalized_title = _normalize_title(title)
        if normalized_title in seen_titles:
            original_title, original_page = seen_titles[normalized_title]
            issues.append(
                LintIssue(
                    code="duplicate-title",
                    severity="error",
                    page_path=page,
                    message=f"Page title {title!r} duplicates {original_title!r} in {original_page.name}.",
                )
            )
        else:
            seen_titles[normalized_title] = (title, page)

        for alias in _frontmatter_list_values(text, "aliases"):
            normalized_alias = _normalize_title(alias)
            if normalized_alias in seen_aliases:
                original_alias, original_page = seen_aliases[normalized_alias]
                issues.append(
                    LintIssue(
                        code="duplicate-alias",
                        severity="error",
                        page_path=page,
                        message=f"Alias {alias!r} duplicates {original_alias!r} in {original_page.name}.",
                    )
                )
            else:
                seen_aliases[normalized_alias] = (alias, page)
    return issues


def _index_completeness_issues(wiki: Path, pages: list[Path]) -> list[LintIssue]:
    """Compare the generated index section with pages on disk.

    The check only runs when MemoWeaver's generated index markers are present.
    Freshly initialized wikis do not have a generated section until pages are
    written, and lint should not require users to hand-maintain that section.
    """

    index_path = wiki / "index.md"
    if not index_path.exists():
        return []
    text = index_path.read_text(encoding="utf-8")
    section = _marked_section(text, start=INDEX_START, end=INDEX_END)
    if section is None:
        return []

    actual_paths = {page.relative_to(wiki).as_posix() for page in pages}
    indexed_paths = {_index_link_to_relative_path(link) for link in _wikilinks(section)}
    indexed_paths = {path for path in indexed_paths if path is not None}
    issues: list[LintIssue] = []

    for indexed_path in sorted(indexed_paths - actual_paths):
        issues.append(
            LintIssue(
                code="index-missing-page",
                severity="error",
                page_path=Path("index.md"),
                message=f"Generated index points to {indexed_path}, but that page does not exist on disk.",
            )
        )
    for page in pages:
        relative = page.relative_to(wiki).as_posix()
        if relative not in indexed_paths:
            issues.append(
                LintIssue(
                    code="index-unlisted-page",
                    severity="warning",
                    page_path=page,
                    message=f"Page {relative} is not listed in the generated index section.",
                )
            )
    return issues


def _scan_pages(wiki: Path) -> list[Path]:
    pages: list[Path] = []
    for directory in CONTENT_DIRECTORIES:
        root = wiki / directory
        if root.exists():
            pages.extend(path for path in sorted(root.rglob("*.md")) if path.is_file())
    return sorted(pages)


def _build_title_index(pages: list[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for page in pages:
        for title in _page_titles(page):
            index.setdefault(_normalize_title(title), page)
    return index


def _page_titles(page: Path) -> list[str]:
    text = page.read_text(encoding="utf-8")
    titles: list[str] = []
    frontmatter = _frontmatter(text)
    if "title" in frontmatter:
        titles.append(frontmatter["title"])
    for line in text.splitlines():
        if line.startswith("# "):
            titles.append(line[2:].strip())
            break
    titles.append(page.stem.replace("-", " ").title())
    titles.append(page.stem)
    return [title for title in titles if title]


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value:
            metadata[key.strip()] = value
    return metadata


def _primary_page_title(page: Path, text: str) -> str:
    frontmatter = _frontmatter(text)
    if "title" in frontmatter:
        return frontmatter["title"]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return page.stem.replace("-", " ").title()


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


def _has_frontmatter(text: str) -> bool:
    return bool(_frontmatter(text))


def _wikilinks(text: str) -> list[str]:
    return [match.group(1).strip() for match in WIKILINK_PATTERN.finditer(text) if match.group(1).strip()]


def _marked_section(text: str, *, start: str, end: str) -> str | None:
    start_index = text.find(start)
    end_index = text.find(end)
    if start_index == -1 or end_index <= start_index:
        return None
    return text[start_index + len(start) : end_index]


def _index_link_to_relative_path(link_target: str) -> str | None:
    target = link_target.strip()
    if not any(target.startswith(f"{directory}/") for directory in CONTENT_DIRECTORIES):
        return None
    path = Path(target)
    if path.suffix != ".md":
        path = path.with_suffix(".md")
    return path.as_posix()


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())
