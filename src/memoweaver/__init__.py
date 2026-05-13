"""MemoWeaver package."""

from memoweaver.config import MemoWeaverConfig
from memoweaver.ingest import IngestFileResult, ingest_file
from memoweaver.storage import SourceRecord, SourceRegistry, StorageState, initialize_state
from memoweaver.wiki import WikiInitResult, init_wiki

__all__ = [
    "MemoWeaverConfig",
    "IngestFileResult",
    "SourceRecord",
    "SourceRegistry",
    "StorageState",
    "WikiInitResult",
    "ingest_file",
    "init_wiki",
    "initialize_state",
]

__version__ = "0.1.0"
