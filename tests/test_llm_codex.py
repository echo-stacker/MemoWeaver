from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.ingest import ingest_file
from memoweaver.llm import CodexHTTPProvider, LLMExtraction, extract_document_insights, parse_llm_json_object
from memoweaver.parser import parse_markdown_text
from memoweaver.wiki import init_wiki


class _OneShotCodexHandler(BaseHTTPRequestHandler):
    request_payload: dict | None = None
    response_payload: dict = {}
    auth_header: str | None = None

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTPServer callback name
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.auth_header = self.headers.get("Authorization")
        self.__class__.request_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.__class__.response_payload).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:  # pragma: no cover - keep tests quiet
        return


def _serve_once(response_content: str) -> tuple[str, threading.Thread]:
    _OneShotCodexHandler.request_payload = None
    _OneShotCodexHandler.auth_header = None
    _OneShotCodexHandler.response_payload = {
        "choices": [{"message": {"content": response_content}}],
        "model": "gpt-5.5",
    }
    server = HTTPServer(("127.0.0.1", 0), _OneShotCodexHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}/v1", thread


def _sample_document():
    return parse_markdown_text(
        "# MemoWeaver\n\nMemoWeaver turns raw notes into durable wiki pages.\n\n## Architecture\n\nParser output feeds LLM extraction.\n",
        source_id="src_doc",
        source_path=Path("raw/articles/src_doc.md"),
    )


def test_codex_http_provider_posts_openai_compatible_chat_request() -> None:
    base_url, thread = _serve_once('{"summary":"ok","entities":[],"concepts":[],"claims":[],"relations":[],"suggested_pages":[]}')
    provider = CodexHTTPProvider(base_url=base_url, api_key="test-key", model="gpt-5.5", timeout=5)

    content = provider.complete(system="system prompt", user="user prompt", max_tokens=512)
    thread.join(timeout=2)

    assert json.loads(content)["summary"] == "ok"
    assert _OneShotCodexHandler.auth_header == "Bearer test-key"
    payload = _OneShotCodexHandler.request_payload
    assert payload is not None
    assert payload["model"] == "gpt-5.5"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 512
    assert payload["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_parse_llm_json_object_accepts_markdown_fenced_json() -> None:
    payload = parse_llm_json_object('```json\n{"summary":"hello","entities":[{"name":"MemoWeaver"}]}\n```')

    assert payload["summary"] == "hello"
    assert payload["entities"] == [{"name": "MemoWeaver"}]


def test_extract_document_insights_normalizes_structured_fields() -> None:
    base_url, thread = _serve_once(
        json.dumps(
            {
                "summary": "Builds a wiki from notes.",
                "entities": [{"name": "MemoWeaver", "type": "project"}],
                "concepts": ["LLM-native wiki"],
                "claims": [{"text": "Parser output feeds extraction", "confidence": "0.8"}],
                "relations": [{"source": "Parser", "target": "LLM", "type": "feeds"}],
                "suggested_pages": [{"title": "MemoWeaver Architecture", "reason": "central concept"}],
            }
        )
    )
    provider = CodexHTTPProvider(base_url=base_url, api_key="test-key", model="gpt-5.5", timeout=5)

    extraction = extract_document_insights(_sample_document(), provider=provider)
    thread.join(timeout=2)

    assert isinstance(extraction, LLMExtraction)
    assert extraction.source_id == "src_doc"
    assert extraction.summary == "Builds a wiki from notes."
    assert extraction.entities == [{"name": "MemoWeaver", "type": "project"}]
    assert extraction.concepts == ["LLM-native wiki"]
    assert extraction.claims == [{"text": "Parser output feeds extraction", "confidence": 0.8}]
    assert extraction.relations == [{"source": "Parser", "target": "LLM", "type": "feeds"}]
    assert extraction.suggested_pages == [{"title": "MemoWeaver Architecture", "reason": "central concept"}]
    assert extraction.to_dict()["schema_version"] == 1


def test_cli_extract_uses_codex_http_and_outputs_json_summary(tmp_path: Path, monkeypatch) -> None:
    base_url, thread = _serve_once(
        json.dumps(
            {
                "summary": "CLI extraction works.",
                "entities": [{"name": "MemoWeaver", "type": "project"}],
                "concepts": ["local Codex HTTP"],
                "claims": [],
                "relations": [],
                "suggested_pages": ["MemoWeaver"],
            }
        )
    )
    monkeypatch.setenv("CLIPROXYAPI_BASE_URL", base_url)
    monkeypatch.setenv("CLIPROXYAPI_API_KEY", "test-key")

    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# CLI Extract\n\nMemoWeaver calls local Codex HTTP.\n", encoding="utf-8")
    init_wiki(wiki_path)
    ingest = ingest_file(source_path, wiki_path=wiki_path, title="CLI Extract")

    result = CliRunner().invoke(cli, ["extract", str(ingest.raw_path)])
    thread.join(timeout=2)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["source_id"] == ingest.record.source_id
    assert payload["summary"] == "CLI extraction works."
    assert payload["entity_count"] == 1
    assert payload["concept_count"] == 1
    assert payload["suggested_page_count"] == 1
