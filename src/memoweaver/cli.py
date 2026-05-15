from __future__ import annotations

from pathlib import Path
import json

import click

from memoweaver import __version__
from memoweaver.ingest import ingest_file
from memoweaver.llm import CodexHTTPProvider, LLM_SCHEMA_VERSION, extract_document_insights
from memoweaver.lint import lint_wiki
from memoweaver.parser import parse_wiki_raw_source
from memoweaver.query import ask_wiki
from memoweaver.resolver import resolve_extraction_pages
from memoweaver.storage import LLMExtractionCache, SourceRegistry
from memoweaver.wiki import init_wiki
from memoweaver.wiki_writer import extraction_from_dict, write_extraction_pages


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


@cli.command()
@click.argument("raw_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def parse(raw_path: Path) -> None:
    """Parse an ingested raw Markdown/TXT source and print a JSON summary.

    The CLI returns a compact summary rather than the full document so it stays
    readable in terminals. Library users can call `parse_wiki_raw_source()` when
    they need the full block/chunk payload for the LLM stage.
    """

    document = parse_wiki_raw_source(raw_path)
    click.echo(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": document.source_id,
                "title": document.title,
                "source_path": str(document.source_path),
                "heading_count": len(document.headings),
                "block_count": len(document.blocks),
                "chunk_count": len(document.chunks),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@cli.command()
@click.argument("raw_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--wiki", "wiki_path", default=None, type=click.Path(path_type=Path), help="MemoWeaver wiki path used for extraction cache.")
@click.option("--model", default=None, help="Local Codex HTTP model name. Defaults to MEMOWEAVER_CODEX_MODEL or gpt-5.5.")
@click.option("--refresh", is_flag=True, help="Ignore any cached extraction and call the LLM again.")
@click.option("--full-json", "full_json", is_flag=True, help="Emit the full extraction payload instead of a compact summary.")
def extract(raw_path: Path, wiki_path: Path | None, model: str | None, refresh: bool, full_json: bool) -> None:
    """Extract structured wiki knowledge via local Codex HTTP/CLIProxyAPI.

    When ``--wiki`` is provided, extraction payloads are stored in
    ``.wiki-state/llm-cache.json`` and reused on later runs with the same
    source/model/schema. Use ``--refresh`` to force a new LLM call.
    """

    document = parse_wiki_raw_source(raw_path)
    provider = CodexHTTPProvider.from_env()
    if model:
        provider = CodexHTTPProvider(
            base_url=provider.base_url,
            api_key=provider.api_key,
            model=model,
            timeout=provider.timeout,
            temperature=provider.temperature,
        )
    cache = LLMExtractionCache.open(wiki_path) if wiki_path is not None else None
    cached = cache.get(document.source_id, model=provider.model, schema_version=LLM_SCHEMA_VERSION) if cache and not refresh else None
    if cached is not None:
        payload = cached
        is_cached = True
    else:
        try:
            extraction = extract_document_insights(document, provider=provider)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        payload = extraction.to_dict()
        if cache is not None:
            payload = cache.put(payload, model=provider.model, schema_version=LLM_SCHEMA_VERSION)
        is_cached = False

    if full_json:
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    click.echo(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": payload.get("source_id", ""),
                "summary": payload.get("summary", ""),
                "entity_count": len(payload.get("entities") or []),
                "concept_count": len(payload.get("concepts") or []),
                "claim_count": len(payload.get("claims") or []),
                "relation_count": len(payload.get("relations") or []),
                "suggested_page_count": len(payload.get("suggested_pages") or []),
                "cached": is_cached,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@cli.command("write-pages")
@click.argument("extraction_path", required=False, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--wiki", "wiki_path", required=True, type=click.Path(path_type=Path), help="MemoWeaver wiki path.")
@click.option("--resolve", "use_resolver", is_flag=True, help="Resolve aliases/existing pages before writing.")
@click.option("--source-id", default=None, help="Load extraction payload from the wiki LLM cache instead of a JSON file.")
@click.option("--model", default="gpt-5.5", show_default=True, help="Model key used when reading cached extraction payloads.")
def write_pages(extraction_path: Path | None, wiki_path: Path, use_resolver: bool, source_id: str | None, model: str) -> None:
    """Write entity/concept Markdown pages from an extraction JSON file or cache.

    Pass EXTRACTION_PATH for fixture/file based usage, or ``--source-id`` to load
    a cached extraction from ``.wiki-state/llm-cache.json``.
    """

    if source_id:
        payload = LLMExtractionCache.open(wiki_path).get(source_id, model=model, schema_version=LLM_SCHEMA_VERSION)
        if payload is None:
            raise click.ClickException(f"No cached extraction for source_id={source_id!r} model={model!r}")
    elif extraction_path is not None:
        payload = json.loads(extraction_path.read_text(encoding="utf-8"))
    else:
        raise click.ClickException("Provide EXTRACTION_PATH or --source-id.")
    extraction = extraction_from_dict(payload)
    plan = resolve_extraction_pages(extraction, wiki_path=wiki_path) if use_resolver else None
    result = write_extraction_pages(extraction, wiki_path=wiki_path, plan=plan)
    click.echo(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


@cli.command("resolve-pages")
@click.argument("extraction_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--wiki", "wiki_path", required=True, type=click.Path(path_type=Path), help="MemoWeaver wiki path.")
def resolve_pages(extraction_path: Path, wiki_path: Path) -> None:
    """Dry-run create/update/skip decisions for extraction JSON.

    This command does not write pages. It exposes the resolver's decision layer so
    contributors can inspect whether extracted entities/concepts would create new
    files, update existing pages, or be skipped as duplicate targets.
    """

    payload = json.loads(extraction_path.read_text(encoding="utf-8"))
    plan = resolve_extraction_pages(extraction_from_dict(payload), wiki_path=wiki_path)
    click.echo(json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True))


@cli.command("ask")
@click.argument("question")
@click.option("--wiki", "wiki_path", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path), help="MemoWeaver wiki path.")
@click.option("--limit", default=5, show_default=True, type=int, help="Maximum matching pages to use as context.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable JSON answer.")
@click.option("--save", is_flag=True, help="Save the answer as a Markdown page under queries/.")
def ask_command(question: str, wiki_path: Path, limit: int, as_json: bool, save: bool) -> None:
    """Ask a question against the maintained wiki."""

    try:
        answer = ask_wiki(question, wiki_path=wiki_path, provider=CodexHTTPProvider.from_env(), limit=limit, save=save)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(answer.to_dict(), ensure_ascii=False, sort_keys=True))
        return
    click.echo(answer.answer)
    if answer.sources:
        click.echo("\nSources:")
        for source in answer.sources:
            click.echo(f"- [[{source.relative_path.removesuffix('.md')}|{source.title}]]")
    if answer.saved_path is not None:
        click.echo(f"\nSaved: {answer.saved_path}")


@cli.command("lint")
@click.argument("wiki_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable JSON report.")
def lint_command(wiki_path: Path, as_json: bool) -> None:
    """Check a MemoWeaver wiki for maintainability issues."""

    report = lint_wiki(wiki_path)
    if as_json:
        click.echo(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        click.echo(f"MemoWeaver lint: {report.issue_count} issue(s), {report.error_count} error(s), {report.warning_count} warning(s)")
        for issue in report.issues:
            click.echo(f"{issue.severity.upper()} {issue.code} {issue.relative_path}: {issue.message}")
    if report.issue_count:
        raise click.exceptions.Exit(1)


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
