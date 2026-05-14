# MemoWeaver

> A headless Python service for building and maintaining LLM-native wikis.

MemoWeaver turns raw knowledge sources—documents, web pages, research reports, notes, transcripts, and code references—into a durable, interlinked Markdown wiki that can be queried and maintained by LLM agents.

It is designed for teams and individuals who want a knowledge base that compounds over time without needing a web frontend. The primary interfaces are Python APIs, CLI commands, scheduled jobs, and file-based Markdown output that can be opened with Obsidian, VS Code, GitHub, or any editor.

## Why MemoWeaver?

Traditional RAG systems often retrieve fragments from raw documents at query time. MemoWeaver follows a different pattern: it compiles knowledge into a maintained wiki first.

Instead of repeatedly asking an LLM to rediscover the same facts, MemoWeaver aims to:

- ingest raw sources once;
- extract entities, concepts, claims, and relationships;
- write durable Markdown pages;
- keep backlinks, indexes, provenance, and update logs current;
- detect duplicates, stale pages, and contradictions;
- expose the resulting knowledge graph to humans and LLM agents.

## Core Idea

```text
Raw Sources
  ↓
Ingestion Pipeline
  ↓
LLM Extraction / Summarization
  ↓
Entity & Concept Resolution
  ↓
Markdown Wiki Writer
  ↓
Index, Backlinks, Provenance, Log
  ↓
CLI / Python API / Scheduled Workers / Agent Query
```

MemoWeaver is intentionally headless. It does not try to become another note-taking app or dashboard. It focuses on the backend maintenance layer of an LLM wiki.

## Planned Features

### 1. Source Ingestion

- Web pages
- Local Markdown files
- PDFs and research reports
- Plain text notes
- Transcripts
- Code or repository documentation
- Batch ingestion from folders

### 2. Wiki Compilation

- Generate entity pages
- Generate concept pages
- Generate comparison pages
- Generate query/synthesis pages
- Maintain cross-links with `[[wikilinks]]`
- Preserve source provenance
- Append chronological maintenance logs

### 3. Knowledge Maintenance

- Duplicate page detection
- Broken link detection
- Orphan page detection
- Tag taxonomy checks
- Stale content checks
- Contradiction surfacing
- Source drift detection

### 4. Query Interfaces

- Python API
- CLI
- Optional local HTTP API
- Agent-friendly JSON outputs
- Markdown answer filing for valuable queries

### 5. Automation

- Cron-friendly commands
- Incremental ingest
- Watch-folder mode
- Scheduled wiki linting
- Scheduled source refresh

## Non-Goals

MemoWeaver is not intended to be:

- a full web frontend;
- a Notion/Obsidian replacement;
- a generic vector database wrapper;
- a one-shot summarizer;
- a closed, hosted SaaS-first product.

It should stay simple, inspectable, local-first, and agent-friendly.

## Proposed Project Structure

```text
memoweaver/
├── README.md
├── pyproject.toml
├── src/
│   └── memoweaver/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── ingest/
│       ├── llm/
│       ├── wiki/
│       ├── graph/
│       ├── lint/
│       └── storage/
├── tests/
├── examples/
└── docs/
```

## Example Wiki Layout

```text
wiki/
├── SCHEMA.md
├── index.md
├── log.md
├── raw/
│   ├── articles/
│   ├── papers/
│   ├── transcripts/
│   └── assets/
├── entities/
├── concepts/
├── comparisons/
└── queries/
```

## Example Usage

> The API below is a design target and may change during early development.

```bash
# Initialize a new wiki
memoweaver init ./wiki --domain "AI research and engineering"

# Register a source in the wiki state before ingestion
memoweaver sources register ./reports/example.pdf --wiki ./wiki --kind pdf --title "Example report"

# Ingest a local Markdown/TXT document
memoweaver ingest ./notes/example.md --wiki ./wiki --title "Example note"
memoweaver ingest ./notes/raw-notes.txt --wiki ./wiki

# Parse an ingested raw source into a structured document summary
memoweaver parse ./wiki/raw/articles/src_abc123.md

# Extract structured knowledge with local Codex HTTP/CLIProxyAPI and cache it in wiki state
export CLIPROXYAPI_BASE_URL=http://127.0.0.1:8317/v1
export CLIPROXYAPI_API_KEY=... # or configure CLIProxyAPI locally
memoweaver extract ./wiki/raw/articles/src_abc123.md --wiki ./wiki --model gpt-5.5
memoweaver extract ./wiki/raw/articles/src_abc123.md --wiki ./wiki --full-json
memoweaver extract ./wiki/raw/articles/src_abc123.md --wiki ./wiki --refresh

# Materialize a saved extraction payload into Markdown pages
memoweaver write-pages ./extraction.json --wiki ./wiki
memoweaver write-pages ./extraction.json --wiki ./wiki --resolve
memoweaver write-pages --wiki ./wiki --source-id src_abc123 --model gpt-5.5

# Check wiki health
memoweaver lint ./wiki
memoweaver lint ./wiki --json

# Dry-run resolver decisions before writing/updating pages
memoweaver resolve-pages ./extraction.json --wiki ./wiki

# Ask a question against the maintained wiki
memoweaver ask "What are the strongest arguments for agentic knowledge bases?" --wiki ./wiki

# Run a maintenance audit
memoweaver lint ./wiki
```

Python API sketch:

```python
from memoweaver import MemoWeaver

wiki = MemoWeaver.open("./wiki")
wiki.ingest("./reports/example.pdf")
answer = wiki.ask("What changed since the last ingest?")
wiki.lint()
```

## Design Principles

1. **Headless first** — no frontend required.
2. **Markdown native** — the wiki remains readable and portable.
3. **Provenance by default** — important claims should trace back to sources.
4. **Agent-friendly** — outputs should be useful to LLM agents and automation.
5. **Local-first** — users should be able to run it on their own machine.
6. **Incremental maintenance** — knowledge should compound instead of being regenerated from scratch.
7. **Small, testable modules** — ingestion, resolution, writing, linting, and querying should be independently testable.

## Roadmap

### Phase 0 — Project Skeleton

- [x] Create Python package layout
- [x] Add CLI entry point
- [x] Add config model
- [x] Add basic test suite

### Phase 1 — Wiki Initialization

- [x] Generate wiki folder structure
- [x] Create `SCHEMA.md`
- [x] Create `index.md`
- [x] Create `log.md`

### Phase 2 — Storage and Source Registry

- [x] Create `.wiki-state/` state layout
- [x] Create `sources.json`
- [x] Create `ingest-history.jsonl`
- [x] Create `llm-cache.json`
- [x] Register sources by SHA-256
- [x] Detect duplicate source content

### Phase 3 — Markdown/TXT Ingestion

- [x] Ingest local Markdown files
- [x] Ingest local TXT files
- [x] Store immutable raw sources
- [x] Write raw-source metadata sidecars
- [x] Skip duplicate content by SHA-256
- [x] Extract title, summary, entities, and concepts
- [x] Generate first wiki pages

### Phase 4 — Parser

- [x] Parse Markdown headings
- [x] Parse Markdown paragraphs
- [x] Preserve fenced code blocks
- [x] Parse plain TXT paragraphs
- [x] Emit structured `ParsedDocument` JSON
- [x] Emit LLM-friendly chunks
- [ ] Preserve Markdown tables as typed blocks
- [ ] Add configurable chunk merging/splitting

### Phase 5 — LLM Integration

- [x] Add pluggable LLM provider interface
- [x] Support OpenAI-compatible endpoints
- [x] Support local Codex HTTP/CLIProxyAPI gateway
- [x] Add structured extraction schemas
- [x] Persist extraction results into wiki state/cache
- [x] Reuse cached extractions by source/model/schema
- [x] Add `extract --refresh` and `extract --full-json`
- [x] Let `write-pages` load cached extractions by `--source-id`

### Phase 6 — Wiki Page Writer

- [x] Create entity pages from extraction output
- [x] Create concept pages from extraction output
- [x] Create suggested pages from extraction output
- [x] Preserve human edits outside generated blocks
- [x] Add `write-pages` CLI command
- [ ] Backlink generation
- [x] Index maintenance
- [x] Broken link detection
- [x] Orphan page detection
- [ ] Duplicate page detection

### Phase 7 — Resolver

- [x] Scan existing entity/concept pages
- [x] Build slug/title/alias lookup maps
- [x] Generate create/update/skip change plans
- [x] Add resolver dry-run CLI
- [x] Feed resolver plans into writer execution
- [x] Merge source_ids across updates
- [ ] Add canonical alias/collision policies

### Phase 8 — Lint and Health Checks

- [x] Add `lint` CLI command
- [x] Emit JSON health reports
- [x] Detect broken wikilinks
- [x] Detect missing page frontmatter
- [x] Detect isolated orphan pages
- [ ] Index completeness checks
- [ ] Source drift checks

### Phase 9 — Query and Automation

## Status

MemoWeaver is currently in early implementation. It can initialize a Markdown wiki, create the file-based state store, register sources by SHA-256, ingest local Markdown/TXT files into immutable raw-source storage, parse raw sources into structured blocks/chunks, call a local Codex HTTP/CLIProxyAPI endpoint for structured knowledge extraction, persist/reuse extraction payloads in `.wiki-state/llm-cache.json`, materialize extraction output or cached source IDs into entity/concept Markdown pages, dry-run resolver create/update/skip decisions, apply resolver plans during page writes, merge page `source_ids` across updates, maintain generated index entries and chronological write logs, lint wiki health for broken links/frontmatter/orphans, and detect duplicate source content. The next goal is to add canonical alias/collision policies and richer lint checks so long-lived wikis remain auditable as pages accumulate.

## License

TBD.

## Name

**MemoWeaver** means weaving fragments of memory into a durable knowledge fabric.
