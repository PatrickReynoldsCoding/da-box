import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden_items (
    item_id TEXT PRIMARY KEY
);
"""


class Store:
    """Small key/value + hidden-items store on top of SQLite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # A new connection per call keeps this safe from FastAPI's thread pool.
        connection = sqlite3.connect(self._db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get(self, key: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    def delete(self, key: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM settings WHERE key = ?", (key,))

    def hidden_item_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT item_id FROM hidden_items").fetchall()
        return {row[0] for row in rows}

    def set_hidden(self, item_id: str, hidden: bool) -> None:
        with self._connect() as connection:
            if hidden:
                connection.execute("INSERT OR IGNORE INTO hidden_items (item_id) VALUES (?)", (item_id,))
            else:
                connection.execute("DELETE FROM hidden_items WHERE item_id = ?", (item_id,))
