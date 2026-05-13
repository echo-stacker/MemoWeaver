from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PARSER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ParsedBlock:
    """A typed span of source text.

    Blocks are the parser's stable internal unit: headings, paragraphs, code
    fences, and later tables/lists can all be represented without forcing the LLM
    stage to re-parse raw Markdown. Line numbers are 1-based and inclusive so a
    future UI or provenance report can point back to the original source.
    """

    kind: str
    text: str
    start_line: int
    end_line: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class Heading:
    """A Markdown heading discovered in source order."""

    level: int
    text: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "text": self.text, "line": self.line}


@dataclass(frozen=True)
class ParsedChunk:
    """LLM-friendly chunk derived from one or more parsed blocks.

    The MVP uses a conservative one-block-to-one-chunk mapping. That is not fancy,
    and that is the point: downstream modules get predictable chunks now, while a
    later chunker can merge/split blocks without changing `ParsedDocument`.
    """

    source_id: str
    text: str
    start_line: int
    end_line: int
    block_kinds: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "block_kinds": list(self.block_kinds),
        }


@dataclass(frozen=True)
class ParsedDocument:
    """Structured representation consumed by future LLM/wiki-writing modules."""

    source_id: str
    source_path: Path
    title: str | None
    headings: list[Heading]
    blocks: list[ParsedBlock]
    chunks: list[ParsedChunk]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PARSER_SCHEMA_VERSION,
            "source_id": self.source_id,
            "source_path": str(self.source_path),
            "title": self.title,
            "headings": [heading.to_dict() for heading in self.headings],
            "blocks": [block.to_dict() for block in self.blocks],
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "metadata": self.metadata,
        }


def parse_wiki_raw_source(raw_path: str | Path) -> ParsedDocument:
    """Parse a raw source copied by `memoweaver ingest`.

    Ingest writes a sidecar metadata file next to each raw source. Reading that
    sidecar here keeps provenance attached to parser output without making the
    parser know about the source registry file format.
    """

    path = Path(raw_path)
    metadata = _read_sidecar_metadata(path)
    source_id = str(metadata.get("source_id") or path.stem)
    document = parse_file(path, source_id=source_id, metadata=metadata)
    if metadata.get("title") and not document.title:
        return ParsedDocument(
            source_id=document.source_id,
            source_path=document.source_path,
            title=str(metadata["title"]),
            headings=document.headings,
            blocks=document.blocks,
            chunks=document.chunks,
            metadata=document.metadata,
        )
    return document


def parse_file(source_path: str | Path, *, source_id: str | None = None, metadata: dict[str, Any] | None = None) -> ParsedDocument:
    """Parse a supported local raw text file.

    This parser intentionally does not attempt full CommonMark compliance. The
    project needs a small, auditable parser that preserves the structures most
    useful to the next LLM stage: headings, paragraphs, and fenced code blocks.
    Complex Markdown features can be added as tested block types later.
    """

    path = Path(source_path)
    text = path.read_text(encoding="utf-8")
    effective_source_id = source_id or path.stem
    if path.suffix.lower() in {".md", ".markdown"}:
        return parse_markdown_text(text, source_id=effective_source_id, source_path=path, metadata=metadata)
    if path.suffix.lower() == ".txt":
        return parse_plain_text(text, source_id=effective_source_id, source_path=path, metadata=metadata)
    raise ValueError(f"Unsupported parse type: {path.suffix or '<no extension>'}")


def parse_markdown_text(
    text: str,
    *,
    source_id: str,
    source_path: Path,
    metadata: dict[str, Any] | None = None,
) -> ParsedDocument:
    """Parse the Markdown subset MemoWeaver needs for its first LLM pipeline."""

    lines = text.splitlines()
    blocks: list[ParsedBlock] = []
    headings: list[Heading] = []
    paragraph_lines: list[str] = []
    paragraph_start: int | None = None
    in_code = False
    code_lines: list[str] = []
    code_start = 0
    code_language = ""

    def flush_paragraph(end_line: int) -> None:
        nonlocal paragraph_lines, paragraph_start
        if paragraph_lines and paragraph_start is not None:
            blocks.append(
                ParsedBlock(
                    kind="paragraph",
                    text="\n".join(paragraph_lines).strip(),
                    start_line=paragraph_start,
                    end_line=end_line,
                )
            )
        paragraph_lines = []
        paragraph_start = None

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if in_code:
            if stripped.startswith("```"):
                blocks.append(
                    ParsedBlock(
                        kind="code",
                        text="\n".join(code_lines),
                        start_line=code_start,
                        end_line=index,
                        metadata={"language": code_language},
                    )
                )
                in_code = False
                code_lines = []
                code_language = ""
            else:
                code_lines.append(line)
            continue

        if stripped.startswith("```"):
            flush_paragraph(index - 1)
            in_code = True
            code_start = index
            code_language = stripped[3:].strip()
            code_lines = []
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush_paragraph(index - 1)
            heading = Heading(level=len(heading_match.group(1)), text=heading_match.group(2), line=index)
            headings.append(heading)
            blocks.append(
                ParsedBlock(
                    kind="heading",
                    text=f"{'#' * heading.level} {heading.text}",
                    start_line=index,
                    end_line=index,
                    metadata={"level": heading.level, "text": heading.text},
                )
            )
            continue

        if not stripped:
            flush_paragraph(index - 1)
            continue

        if paragraph_start is None:
            paragraph_start = index
        paragraph_lines.append(line)

    if in_code:
        blocks.append(
            ParsedBlock(
                kind="code",
                text="\n".join(code_lines),
                start_line=code_start,
                end_line=len(lines),
                metadata={"language": code_language, "closed": False},
            )
        )
    else:
        flush_paragraph(len(lines))

    title = headings[0].text if headings else _first_non_empty_line(lines)
    return _document(source_id, source_path, title, headings, blocks, metadata)


def parse_plain_text(
    text: str,
    *,
    source_id: str,
    source_path: Path,
    metadata: dict[str, Any] | None = None,
) -> ParsedDocument:
    """Parse plain text as blank-line separated paragraphs."""

    lines = text.splitlines()
    blocks: list[ParsedBlock] = []
    paragraph_lines: list[str] = []
    paragraph_start: int | None = None

    def flush(end_line: int) -> None:
        nonlocal paragraph_lines, paragraph_start
        if paragraph_lines and paragraph_start is not None:
            blocks.append(ParsedBlock("paragraph", "\n".join(paragraph_lines).strip(), paragraph_start, end_line))
        paragraph_lines = []
        paragraph_start = None

    for index, line in enumerate(lines, start=1):
        if not line.strip():
            flush(index - 1)
            continue
        if paragraph_start is None:
            paragraph_start = index
        paragraph_lines.append(line)
    flush(len(lines))

    return _document(source_id, source_path, _first_non_empty_line(lines), [], blocks, metadata)


def _document(
    source_id: str,
    source_path: Path,
    title: str | None,
    headings: list[Heading],
    blocks: list[ParsedBlock],
    metadata: dict[str, Any] | None,
) -> ParsedDocument:
    chunks = [
        ParsedChunk(
            source_id=source_id,
            text=block.text,
            start_line=block.start_line,
            end_line=block.end_line,
            block_kinds=(block.kind,),
        )
        for block in blocks
        if block.text.strip()
    ]
    return ParsedDocument(
        source_id=source_id,
        source_path=source_path,
        title=title,
        headings=headings,
        blocks=blocks,
        chunks=chunks,
        metadata=dict(metadata or {}),
    )


def _read_sidecar_metadata(raw_path: Path) -> dict[str, Any]:
    metadata_path = raw_path.with_name(f"{raw_path.stem}.metadata.json")
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _first_non_empty_line(lines: list[str]) -> str | None:
    for line in lines:
        if line.strip():
            return line.strip().lstrip("# ").strip()
    return None
