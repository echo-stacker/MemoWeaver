from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from memoweaver.cli import cli
from memoweaver.ingest import ingest_file
from memoweaver.parser import parse_file
from memoweaver.wiki import init_wiki


def test_ingest_jsonl_news_archive_preserves_source_and_kind(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "2026-05-14.jsonl"
    source_path.write_text(
        json.dumps(
            {
                "source": "cls",
                "source_name": "财联社",
                "id": "2370824",
                "date": "2026-05-14",
                "time": "09:30:03",
                "title": "绿电概念强势延续 大唐发电7连板",
                "content": "财联社5月14日电，绿电概念强势延续，大唐发电7连板。",
                "subjects": ["盘面直播", "绿色电力"],
                "stocks": [{"name": "大唐发电", "code": "601991"}],
                "url": "https://api3.cls.cn/share/article/2370824",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    init_wiki(wiki_path)

    result = ingest_file(source_path, wiki_path=wiki_path, title="财联社快讯 2026-05-14")

    assert result.record.kind == "jsonl-news"
    assert result.raw_path.name == f"{result.record.source_id}.jsonl"
    assert result.raw_path.read_text(encoding="utf-8") == source_path.read_text(encoding="utf-8")
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["kind"] == "jsonl-news"


def test_parse_jsonl_news_archive_creates_llm_friendly_daily_blocks(tmp_path: Path) -> None:
    source_path = tmp_path / "2026-05-14.jsonl"
    rows = [
        {
            "source": "cls",
            "source_name": "财联社",
            "id": "2370824",
            "date": "2026-05-14",
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
            "date": "2026-05-14",
            "time": "18:18:14",
            "title": "中船特气提示短期下跌风险",
            "content": "公司表示尚未签署新的长期或大额实质性订单协议。",
            "subjects": ["A股公告速递"],
            "stocks": [{"name": "中船特气", "code": "688146"}],
            "url": "https://api3.cls.cn/share/article/2371501",
        },
    ]
    source_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    document = parse_file(source_path, source_id="cls-2026-05-14")

    assert document.title == "财联社 2026-05-14 新闻归档"
    assert document.metadata["item_count"] == 2
    assert document.metadata["sources"] == ["财联社"]
    assert [heading.text for heading in document.headings] == [
        "财联社 2026-05-14 新闻归档",
        "09:30:03｜绿电概念强势延续 大唐发电7连板",
        "18:18:14｜中船特气提示短期下跌风险",
    ]
    assert any(block.kind == "jsonl_record" and block.metadata["item_id"] == "2370824" for block in document.blocks)
    first_record_chunk = next(chunk for chunk in document.chunks if chunk.block_kinds == ("jsonl_record",))
    assert "主题: 盘面直播，绿色电力" in first_record_chunk.text
    assert "股票: 大唐发电(601991)" in first_record_chunk.text
    assert "url: https://api3.cls.cn/share/article/2370824" in first_record_chunk.text


def test_cli_parse_accepts_ingested_cls_jsonl_archive(tmp_path: Path) -> None:
    wiki_path = tmp_path / "wiki"
    source_path = tmp_path / "2026-05-14.jsonl"
    source_path.write_text(
        json.dumps(
            {
                "source": "cls",
                "source_name": "财联社",
                "id": "2370824",
                "date": "2026-05-14",
                "time": "09:30:03",
                "title": "绿电概念强势延续 大唐发电7连板",
                "content": "财联社5月14日电，绿电概念强势延续，大唐发电7连板。",
                "subjects": ["盘面直播"],
                "stocks": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    init_wiki(wiki_path)
    result = ingest_file(source_path, wiki_path=wiki_path, title="财联社快讯 2026-05-14")

    parsed = CliRunner().invoke(cli, ["parse", str(result.raw_path)])

    assert parsed.exit_code == 0, parsed.output
    payload = json.loads(parsed.output)
    assert payload["title"] == "财联社 2026-05-14 新闻归档"
    assert payload["block_count"] == 3
    assert payload["chunk_count"] == 3
