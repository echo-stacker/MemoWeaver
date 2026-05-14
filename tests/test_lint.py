from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.lint import lint_wiki
from memoweaver.wiki import init_wiki


def _write_page(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_lint_wiki_reports_broken_wikilinks(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    _write_page(
        wiki_path / "concepts" / "agent-memory.md",
        "---\ntitle: Agent Memory\ntype: concept\n---\n# Agent Memory\n\nSee [[Missing Page]] and [[MemoWeaver]].\n",
    )
    _write_page(
        wiki_path / "entities" / "memoweaver.md",
        "---\ntitle: MemoWeaver\ntype: entity\n---\n# MemoWeaver\n",
    )

    report = lint_wiki(wiki_path)

    assert report.issue_count == 1
    issue = report.issues[0]
    assert issue.code == "broken-wikilink"
    assert issue.severity == "error"
    assert issue.page_path == wiki_path / "concepts" / "agent-memory.md"
    assert "Missing Page" in issue.message


def test_lint_wiki_reports_missing_frontmatter_and_orphans(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    _write_page(wiki_path / "concepts" / "orphan-concept.md", "# Orphan Concept\n\nNo metadata yet.\n")
    _write_page(
        wiki_path / "entities" / "linked-entity.md",
        "---\ntitle: Linked Entity\ntype: entity\n---\n# Linked Entity\n",
    )
    _write_page(
        wiki_path / "concepts" / "hub.md",
        "---\ntitle: Hub\ntype: concept\n---\n# Hub\n\nLinks to [[Linked Entity]].\n",
    )

    report = lint_wiki(wiki_path)
    codes_by_page = {(issue.code, issue.relative_path) for issue in report.issues}

    assert ("missing-frontmatter", "concepts/orphan-concept.md") in codes_by_page
    assert ("orphan-page", "concepts/orphan-concept.md") in codes_by_page
    assert ("orphan-page", "entities/linked-entity.md") not in codes_by_page


def test_lint_wiki_reports_index_entries_missing_from_disk(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    (wiki_path / "index.md").write_text(
        "# Index\n\n"
        "<!-- memoweaver:index:start -->\n\n"
        "## Generated Pages\n\n"
        "### Concepts\n\n"
        "- [[concepts/missing-page|Missing Page]]\n\n"
        "<!-- memoweaver:index:end -->\n",
        encoding="utf-8",
    )

    report = lint_wiki(wiki_path)

    issue = next(issue for issue in report.issues if issue.code == "index-missing-page")
    assert issue.severity == "error"
    assert issue.relative_path == "index.md"
    assert "concepts/missing-page.md" in issue.message


def test_lint_wiki_reports_pages_missing_from_generated_index(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    _write_page(
        wiki_path / "concepts" / "agent-memory.md",
        "---\ntitle: Agent Memory\ntype: concept\n---\n# Agent Memory\n",
    )
    (wiki_path / "index.md").write_text(
        "# Index\n\n"
        "<!-- memoweaver:index:start -->\n\n"
        "## Generated Pages\n\n"
        "<!-- memoweaver:index:end -->\n",
        encoding="utf-8",
    )

    report = lint_wiki(wiki_path)

    issue = next(issue for issue in report.issues if issue.code == "index-unlisted-page")
    assert issue.severity == "warning"
    assert issue.relative_path == "concepts/agent-memory.md"
    assert "not listed" in issue.message


def test_lint_wiki_reports_duplicate_titles_and_aliases(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    _write_page(
        wiki_path / "concepts" / "agent-memory.md",
        "---\ntitle: Agent Memory\ntype: concept\naliases:\n  - Memory Layer\n---\n# Agent Memory\n",
    )
    _write_page(
        wiki_path / "entities" / "agent-memory-entity.md",
        "---\ntitle: Agent Memory\ntype: entity\naliases:\n  - Memory Layer\n---\n# Agent Memory Entity\n",
    )

    report = lint_wiki(wiki_path)
    issues = {(issue.code, issue.relative_path) for issue in report.issues}

    assert ("duplicate-title", "entities/agent-memory-entity.md") in issues
    assert ("duplicate-alias", "entities/agent-memory-entity.md") in issues


def test_lint_report_to_dict_is_json_serializable(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    _write_page(wiki_path / "concepts" / "no-frontmatter.md", "# No Frontmatter\n")

    payload = lint_wiki(wiki_path).to_dict()

    assert payload["wiki_path"] == str(wiki_path)
    assert payload["issue_count"] >= 1
    assert payload["issues"][0]["path"] == "concepts/no-frontmatter.md"
    json.dumps(payload)


def test_lint_cli_outputs_json_report(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    _write_page(wiki_path / "concepts" / "agent-memory.md", "# Agent Memory\n\n[[Missing Page]]\n")

    result = CliRunner().invoke(cli, ["lint", str(wiki_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["issue_count"] == 2
    assert {issue["code"] for issue in payload["issues"]} == {"broken-wikilink", "missing-frontmatter"}


def test_lint_cli_exits_zero_for_healthy_wiki(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    _write_page(
        wiki_path / "concepts" / "agent-memory.md",
        "---\ntitle: Agent Memory\ntype: concept\n---\n# Agent Memory\n",
    )

    result = CliRunner().invoke(cli, ["lint", str(wiki_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["issue_count"] == 0
