from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from memoweaver.parser import ParsedDocument

LLM_SCHEMA_VERSION = 1
DEFAULT_CODEX_BASE_URL = "http://127.0.0.1:8317/v1"
DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_CODEX_CONFIG_PATH = "/opt/homebrew/etc/cliproxyapi.conf"


class LLMProvider(Protocol):
    """Minimal provider contract for structured extraction.

    MemoWeaver will eventually support multiple backends. The first public seam
    is deliberately tiny: given a system prompt and a user prompt, return text.
    Keeping the provider interface narrow makes the LLM module testable without
    binding the rest of the project to OpenAI-specific request/response shapes.
    """

    def complete(self, *, system: str, user: str, max_tokens: int = 1600) -> str:
        """Return raw assistant text for the provided prompts."""


@dataclass(frozen=True)
class CodexHTTPProvider:
    """OpenAI-compatible adapter for the user's local Codex HTTP/CLIProxyAPI.

    The local service used by the user's existing automations listens at
    `http://127.0.0.1:8317/v1` and exposes `/chat/completions`. This class keeps
    the HTTP details in one place so future cloud/local providers can be added by
    implementing `LLMProvider` instead of touching extraction logic.
    """

    base_url: str = DEFAULT_CODEX_BASE_URL
    api_key: str | None = None
    model: str = DEFAULT_CODEX_MODEL
    timeout: int = 90
    temperature: float = 0.2

    @classmethod
    def from_env(cls) -> "CodexHTTPProvider":
        """Create a provider using the local CLIProxyAPI environment convention."""

        return cls(
            base_url=os.environ.get("CLIPROXYAPI_BASE_URL", DEFAULT_CODEX_BASE_URL).rstrip("/"),
            api_key=load_clipproxy_key(),
            model=os.environ.get("MEMOWEAVER_CODEX_MODEL", os.environ.get("CODEX_MODEL", DEFAULT_CODEX_MODEL)),
            timeout=int(os.environ.get("MEMOWEAVER_LLM_TIMEOUT", "90")),
        )

    def complete(self, *, system: str, user: str, max_tokens: int = 1600) -> str:
        if not self.api_key:
            raise RuntimeError("Missing CLIProxyAPI key. Set CLIPROXYAPI_API_KEY or configure CLIProxyAPI.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Codex HTTP response did not contain choices[0].message.content") from exc


@dataclass(frozen=True)
class LLMExtraction:
    """Structured knowledge extracted from one parsed document.

    This is the first LLM-stage contract. It intentionally captures generic wiki
    ingredients rather than MemoWeaver page files: summaries, entities, concepts,
    claims, relations, and suggested pages. The writer/resolver modules can turn
    this neutral structure into durable Markdown later.
    """

    source_id: str
    summary: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    suggested_pages: list[dict[str, Any]] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LLM_SCHEMA_VERSION,
            "source_id": self.source_id,
            "summary": self.summary,
            "entities": self.entities,
            "concepts": self.concepts,
            "claims": self.claims,
            "relations": self.relations,
            "suggested_pages": self.suggested_pages,
            "raw_response": self.raw_response,
        }


def load_clipproxy_key() -> str | None:
    """Load the local CLIProxyAPI key without logging or exposing it.

    Existing local automations use either `CLIPROXYAPI_API_KEY` or a Homebrew
    config file containing an `api-keys:` block. MemoWeaver follows the same
    convention so the first LLM backend works on the user's machine without
    adding project-specific secrets.
    """

    env_key = (os.environ.get("CLIPROXYAPI_API_KEY") or "").strip()
    if env_key:
        return env_key
    config_path = Path(os.environ.get("CLIPROXYAPI_CONFIG", DEFAULT_CODEX_CONFIG_PATH))
    if not config_path.exists():
        return None
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"api-keys:\s*\n\s*-\s*([^\s#]+)", text)
    if match:
        return match.group(1).strip().strip('"\'')
    return None


def extract_document_insights(document: ParsedDocument, *, provider: LLMProvider | None = None) -> LLMExtraction:
    """Ask an LLM to extract wiki-ready knowledge from a parsed document."""

    provider = provider or CodexHTTPProvider.from_env()
    system = (
        "You are MemoWeaver's structured knowledge extraction engine. "
        "Return only one valid JSON object. Do not wrap it in prose. "
        "Extract durable wiki ingredients from the parsed source: summary, entities, concepts, claims, relations, suggested_pages."
    )
    user = json.dumps(
        {
            "task": "Extract structured knowledge for a headless Markdown wiki.",
            "output_schema": {
                "summary": "short document summary",
                "entities": [{"name": "entity name", "type": "person/org/project/place/other", "description": "optional"}],
                "concepts": ["important concepts or topics"],
                "claims": [{"text": "claim or fact", "confidence": 0.0}],
                "relations": [{"source": "entity/concept", "target": "entity/concept", "type": "relationship"}],
                "suggested_pages": [{"title": "wiki page title", "reason": "why this page should exist"}],
            },
            "document": {
                "source_id": document.source_id,
                "title": document.title,
                "headings": [heading.to_dict() for heading in document.headings],
                "chunks": [chunk.to_dict() for chunk in document.chunks],
            },
        },
        ensure_ascii=False,
    )
    content = provider.complete(system=system, user=user, max_tokens=1800)
    payload = parse_llm_json_object(content)
    return extraction_from_payload(document.source_id, payload)


def parse_llm_json_object(text: str) -> dict[str, Any]:
    """Parse an LLM JSON object with light fenced-code/prose tolerance."""

    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM extraction response must be a JSON object")
    return payload


def extraction_from_payload(source_id: str, payload: dict[str, Any]) -> LLMExtraction:
    """Normalize flexible LLM JSON into the stable `LLMExtraction` schema."""

    return LLMExtraction(
        source_id=source_id,
        summary=str(payload.get("summary") or "").strip(),
        entities=_dict_list(payload.get("entities")),
        concepts=_string_list(payload.get("concepts")),
        claims=[_normalize_claim(row) for row in _dict_list(payload.get("claims"))],
        relations=_dict_list(payload.get("relations")),
        suggested_pages=_suggested_pages(payload.get("suggested_pages")),
        raw_response=payload,
    )


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_claim(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    if "confidence" in normalized:
        try:
            normalized["confidence"] = float(normalized["confidence"])
        except (TypeError, ValueError):
            normalized["confidence"] = 0.0
    return normalized


def _suggested_pages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    pages: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            if title:
                pages.append(dict(item))
        elif str(item).strip():
            pages.append({"title": str(item).strip(), "reason": "suggested by LLM"})
    return pages
