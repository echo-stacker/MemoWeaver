from __future__ import annotations

from pathlib import Path

import click

from memoweaver import __version__
from memoweaver.ingest import ingest_file
from memoweaver.storage import SourceRegistry
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


@cli.command()
@click.argument("source_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--wiki", "wiki_path", required=True, type=click.Path(path_type=Path), help="MemoWeaver wiki path.")
@click.option("--title", default=None, help="Optional human-readable source title.")
def ingest(source_path: Path, wiki_path: Path, title: str | None) -> None:
    """Ingest a local Markdown or TXT source into a wiki.

    This is the first end-to-end data-entry command. It intentionally accepts
    only local `.md`, `.markdown`, and `.txt` files; richer source types should
    get their own tested adapters instead of making this path ambiguous.
    """

    try:
        result = ingest_file(source_path, wiki_path=wiki_path, title=title)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if result.created:
        click.echo(f"Ingested source: source_id={result.record.source_id} raw_path={result.raw_path}")
    else:
        click.echo(f"Duplicate source: source_id={result.record.source_id} raw_path={result.raw_path}")


@cli.group()
def sources() -> None:
    """Inspect and maintain the source registry."""


@sources.command("register")
@click.argument("source_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--wiki", "wiki_path", required=True, type=click.Path(path_type=Path), help="MemoWeaver wiki path.")
@click.option("--kind", default="file", show_default=True, help="Source kind, such as markdown, text, pdf, or url.")
@click.option("--title", default=None, help="Optional human-readable source title.")
def register_source(source_path: Path, wiki_path: Path, kind: str, title: str | None) -> None:
    """Register SOURCE_PATH in the wiki state without ingesting it.

    This command is intentionally low-level. It lets contributors verify the
    Phase 2 storage layer before Phase 3 starts copying raw files and parsing
    Markdown/TXT content.
    """

    registry = SourceRegistry.open(wiki_path)
    result = registry.register_file(source_path, kind=kind, title=title)
    if result.created:
        click.echo(f"Registered source: source_id={result.record.source_id} sha256={result.record.sha256}")
    else:
        click.echo(f"Duplicate source: source_id={result.record.source_id} sha256={result.record.sha256}")
