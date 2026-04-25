"""SQLite-backed result cache keyed by (file hash, pixcull version). V0.3+."""

from pathlib import Path


def cache_key(path: Path) -> str:
    """Derive stable key: sha1 of file mtime + size (fast, no full read)."""
    raise NotImplementedError("V0.3: cache_key")


def get_cached(project_db: Path, key: str) -> dict | None:
    raise NotImplementedError("V0.3: get_cached")


def put_cached(project_db: Path, key: str, result: dict) -> None:
    raise NotImplementedError("V0.3: put_cached")
