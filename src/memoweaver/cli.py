from __future__ import annotations

from pathlib import Path

import click

from memoweaver import __version__
from memoweaver.wiki import init_wiki


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="memoweaver")
def cli() -> None:
    """Build and maintain LLM-native Markdown wikis."""


@cli.command()
@click.argument("wiki_path", type=click.Path(path_type=Path))
@click.option("--domain", default=None, help="Knowledge domain described by this wiki.")
def init(wiki_path: Path, domain: str | None) -> None:
    """Initialize a MemoWeaver wiki directory."""

    result = init_wiki(wiki_path, domain=domain)
    click.echo(f"Initialized MemoWeaver wiki: {result.wiki_path}")
    click.echo(f"Created directories: {len(result.created_directories)}")
    click.echo(f"Created files: {len(result.created_files)}")
