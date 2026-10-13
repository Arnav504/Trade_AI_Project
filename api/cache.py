"""SQLite cache of completed live briefs, keyed by normalized focus."""
import json
import os
import sqlite3
from pathlib import Path

from config import DATA_DIR


def cache_path() -> Path:
    override = os.environ.get("ASAN_CACHE_PATH", "").strip()
    if override:
        return Path(override)
    return DATA_DIR / "brief_cache.sqlite"


def _connect() -> sqlite3.Connection:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS briefs (
            query_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def cache_get(query: str) -> dict | None:
    key = normalize_query(query)
    conn = _connect()
    try:
        row = conn.execute("SELECT payload FROM briefs WHERE query_key = ?", (key,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return json.loads(row[0])


def cache_put(query: str, payload: dict) -> None:
    key = normalize_query(query)
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO briefs (query_key, payload) VALUES (?, ?)",
            (key, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()
