from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.news_archive import ingest_news_archive, resolve_news_archive_path
from memoweaver.wiki import init_wiki


def _write_archive(repo: Path, date: str = "2026-05-14") -> Path:
    data_path = repo / "sources" / "cls" / "data" / date[:4] / f"{date}.jsonl"
    data_path.parent.mkdir(parents=True)
    rows = [
        {
            "source": "cls",
            "source_name": "财联社",
            "id": "2370824",
            "date": date,
            "time": "09:30:03",
            "title": "绿电概念强势延续 大唐发电7连板",
            "content": "财联社5月14日电，绿电概念强势延续，大唐发电7连板。",
            "subjects": ["盘面直播", "绿色电力"],
            "stocks": [{"name": "大唐发电", "code": "601991"}],
            "url": "https://api3.cls.cn/share/article/2370824",
        },
        {
            "source": "cls",
            "source_name": "财联社",
            "id": "2371501",
            "date": date,
            "time": "18:18:14",
            "title": "中船特气提示短期下跌风险",
            "content": "公司表示尚未签署新的长期或大额实质性订单协议。",
            "subjects": ["A股公告速递"],
            "stocks": [{"name": "中船特气", "code": "688146"}],
        },
    ]
    data_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return data_path


def test_resolve_news_archive_path_uses_source_registry_pattern(tmp_path: Path) -> None:
    repo = tmp_path / "market-archive"
    archive_path = _write_archive(repo)
    registry = repo / "manifests" / "source_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "sources": {
                    "cls": {
                        "name": "财联社",
                        "enabled": True,
                        "data_glob": "sources/cls/data/{year}/{date}.jsonl",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert resolve_news_archive_path(repo, date="2026-05-14", source="cls") == archive_path


def test_ingest_news_archive_imports_and_parses_daily_jsonl(tmp_path: Path) -> None:
    repo = tmp_path / "market-archive"
    _write_archive(repo)
    wiki = tmp_path / "wiki"
    init_wiki(wiki)

    result = ingest_news_archive(repo, wiki_path=wiki, date="2026-05-14", source="cls")

    assert result.source == "cls"
    assert result.date == "2026-05-14"
    assert result.created is True
    assert result.record.kind == "jsonl-news"
    assert result.raw_path.exists()
    assert result.document.title == "财联社 2026-05-14 新闻归档"
    assert result.item_count == 2
    assert result.block_count == 5
    assert result.chunk_count == 5
    assert result.title == "财联社快讯 2026-05-14"


def test_cli_ingest_news_archive_reports_json_summary(tmp_path: Path) -> None:
    repo = tmp_path / "market-archive"
    _write_archive(repo)
    wiki = tmp_path / "wiki"
    init_wiki(wiki)

    result = CliRunner().invoke(
        cli,
        [
            "ingest-news-archive",
            str(repo),
            "--wiki",
            str(wiki),
            "--date",
            "2026-05-14",
            "--source",
            "cls",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["source"] == "cls"
    assert payload["date"] == "2026-05-14"
    assert payload["title"] == "财联社快讯 2026-05-14"
    assert payload["item_count"] == 2
    assert payload["block_count"] == 5
    assert payload["raw_path"].endswith(".jsonl")
