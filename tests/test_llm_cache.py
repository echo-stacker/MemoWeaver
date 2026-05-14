from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.ingest import ingest_file
from memoweaver.llm import LLMExtraction
from memoweaver.storage import LLMExtractionCache
from memoweaver.wiki import init_wiki


class _CountingCodexHandler(BaseHTTPRequestHandler):
    request_count = 0
    response_payload: dict = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback
        self.__class__.request_count += 1
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.__class__.response_payload).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:  # pragma: no cover
        return


def _serve_requests(response_content: str, count: int = 1) -> tuple[str, threading.Thread]:
    _CountingCodexHandler.request_count = 0
    _CountingCodexHandler.response_payload = {"choices": [{"message": {"content": response_content}}]}
    server = HTTPServer(("127.0.0.1", 0), _CountingCodexHandler)

    def run() -> None:
        for _ in range(count):
            server.handle_request()
        server.server_close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}/v1", thread


def _extraction(source_id: str = "src_demo") -> LLMExtraction:
    return LLMExtraction(
        source_id=source_id,
        summary="Cached extraction.",
        entities=[{"name": "MemoWeaver", "type": "project"}],
        concepts=["LLM cache"],
        claims=[],
        relations=[],
        suggested_pages=[{"title": "MemoWeaver Cache", "reason": "cache test"}],
    )


def test_llm_extraction_cache_round_trips_payload_by_source_model_and_schema(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    cache = LLMExtractionCache.open(wiki_path)

    cache.put(_extraction(), model="gpt-5.5", schema_version=1)

    cached = cache.get("src_demo", model="gpt-5.5", schema_version=1)
    assert cached is not None
    assert cached["source_id"] == "src_demo"
    assert cached["summary"] == "Cached extraction."
    assert cached["entities"] == [{"name": "MemoWeaver", "type": "project"}]
    assert cache.get("src_demo", model="other-model", schema_version=1) is None


def test_extract_cli_writes_and_reuses_cache_when_wiki_is_provided(tmp_path: Path, monkeypatch) -> None:
    response = json.dumps({"summary": "Stored once.", "entities": [], "concepts": ["cache"], "claims": [], "relations": [], "suggested_pages": []})
    base_url, thread = _serve_requests(response, count=1)
    monkeypatch.setenv("CLIPROXYAPI_BASE_URL", base_url)
    monkeypatch.setenv("CLIPROXYAPI_API_KEY", "test-key")

    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# Cache Me\n\nMemoWeaver should not call the LLM twice.\n", encoding="utf-8")
    init_wiki(wiki_path)
    ingest = ingest_file(source_path, wiki_path=wiki_path, title="Cache Me")
    runner = CliRunner()

    first = runner.invoke(cli, ["extract", str(ingest.raw_path), "--wiki", str(wiki_path), "--model", "gpt-5.5"])
    second = runner.invoke(cli, ["extract", str(ingest.raw_path), "--wiki", str(wiki_path), "--model", "gpt-5.5"])
    thread.join(timeout=2)

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert _CountingCodexHandler.request_count == 1
    assert json.loads(first.output)["cached"] is False
    second_payload = json.loads(second.output)
    assert second_payload["cached"] is True
    assert second_payload["summary"] == "Stored once."


def test_extract_cli_full_json_outputs_cached_extraction_payload(tmp_path: Path, monkeypatch) -> None:
    response = json.dumps({"summary": "Full payload.", "entities": [{"name": "MemoWeaver"}], "concepts": [], "claims": [], "relations": [], "suggested_pages": []})
    base_url, thread = _serve_requests(response, count=1)
    monkeypatch.setenv("CLIPROXYAPI_BASE_URL", base_url)
    monkeypatch.setenv("CLIPROXYAPI_API_KEY", "test-key")

    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "note.md"
    source_path.write_text("# Full JSON\n", encoding="utf-8")
    init_wiki(wiki_path)
    ingest = ingest_file(source_path, wiki_path=wiki_path)

    result = CliRunner().invoke(cli, ["extract", str(ingest.raw_path), "--wiki", str(wiki_path), "--full-json"])
    thread.join(timeout=2)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["source_id"] == ingest.record.source_id
    assert payload["summary"] == "Full payload."
    assert payload["entities"] == [{"name": "MemoWeaver"}]


def test_write_pages_cli_can_materialize_cached_extraction_by_source_id(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    init_wiki(wiki_path)
    LLMExtractionCache.open(wiki_path).put(_extraction(), model="gpt-5.5", schema_version=1)

    result = CliRunner().invoke(cli, ["write-pages", "--wiki", str(wiki_path), "--source-id", "src_demo", "--model", "gpt-5.5"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["created_count"] == 3
    assert "entities/memoweaver.md" in payload["written_pages"]
    assert wiki_path.joinpath("index.md").read_text(encoding="utf-8").count("[[entities/memoweaver|MemoWeaver]]") == 1
