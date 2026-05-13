from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.config import MemoWeaverConfig
from memoweaver.wiki import init_wiki


def test_default_config_points_to_wiki_directory(tmp_path: Path) -> None:
    config = MemoWeaverConfig.default(tmp_path / "wiki", domain="AI research")

    assert config.wiki_path == tmp_path / "wiki"
    assert config.domain == "AI research"
    assert config.llm_provider == "none"


def test_init_wiki_creates_expected_layout_and_markdown_files(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"

    result = init_wiki(wiki_path, domain="A-share research")

    assert result.wiki_path == wiki_path
    for directory in [
        "raw/articles",
        "raw/papers",
        "raw/transcripts",
        "raw/assets",
        "entities",
        "concepts",
        "comparisons",
        "queries",
    ]:
        assert (wiki_path / directory).is_dir()

    schema = (wiki_path / "SCHEMA.md").read_text(encoding="utf-8")
    index = (wiki_path / "index.md").read_text(encoding="utf-8")
    log = (wiki_path / "log.md").read_text(encoding="utf-8")

    assert "# MemoWeaver Wiki Schema" in schema
    assert "Domain: A-share research" in index
    assert "Wiki initialized" in log


def test_init_wiki_is_idempotent_and_preserves_existing_index(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path, domain="First domain")
    index_path = wiki_path / "index.md"
    index_path.write_text("# Custom Index\n", encoding="utf-8")

    init_wiki(wiki_path, domain="Second domain")

    assert index_path.read_text(encoding="utf-8") == "# Custom Index\n"
    assert (wiki_path / "SCHEMA.md").exists()
    assert (wiki_path / "log.md").exists()


def test_cli_init_creates_wiki_and_reports_path(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    runner = CliRunner()

    result = runner.invoke(cli, ["init", str(wiki_path), "--domain", "Local knowledge"])

    assert result.exit_code == 0
    assert "Initialized MemoWeaver wiki" in result.output
    assert str(wiki_path) in result.output
    assert (wiki_path / "SCHEMA.md").exists()
    assert (wiki_path / "index.md").exists()
    assert (wiki_path / "log.md").exists()


def test_cli_version_command() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "memoweaver" in result.output.lower()
