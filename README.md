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

# Ingest a document or URL
memoweaver ingest ./reports/example.pdf --wiki ./wiki
memoweaver ingest https://example.com/article --wiki ./wiki

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

### Phase 2 — Markdown Ingestion

- [ ] Ingest local Markdown files
- [ ] Store immutable raw sources
- [ ] Extract title, summary, entities, and concepts
- [ ] Generate first wiki pages

### Phase 3 — LLM Integration

- [ ] Add pluggable LLM provider interface
- [ ] Support OpenAI-compatible endpoints
- [ ] Support local model gateways
- [ ] Add structured extraction schemas

### Phase 4 — Wiki Maintenance

- [ ] Backlink generation
- [ ] Index maintenance
- [ ] Broken link detection
- [ ] Orphan page detection
- [ ] Duplicate page detection

### Phase 5 — Query and Automation

- [ ] CLI query command
- [ ] Optional local HTTP API
- [ ] Scheduled ingest examples
- [ ] Agent integration examples

## Status

MemoWeaver is currently in the design/bootstrap stage. The initial goal is to build a minimal Python package that can initialize a wiki, ingest Markdown sources, and maintain index/log files reliably.

## License

TBD.

## Name

**MemoWeaver** means weaving fragments of memory into a durable knowledge fabric.
