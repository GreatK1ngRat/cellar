"""SQLite persistence for Cellar.

One file, one table. SQLite is a library, not a service, so there is no
separate database container -- this module just points at a file that lives
on a mounted Docker volume so it survives container rebuilds.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cellar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS wines (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    producer           TEXT,
    type               TEXT NOT NULL,
    vintage            TEXT,
    region             TEXT,
    grape              TEXT,
    price              TEXT,
    rating             REAL,
    tasted_at          TEXT,
    where_tasted       TEXT,
    source             TEXT,
    notes              TEXT,
    image_url          TEXT,
    image_source       TEXT,
    image_checked_at   TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_wines_type ON wines(type);
CREATE INDEX IF NOT EXISTS idx_wines_tasted_at ON wines(tasted_at);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


WINE_FIELDS = [
    "name", "producer", "type", "vintage", "region", "grape", "price",
    "rating", "tasted_at", "where_tasted", "source", "notes",
    "image_url", "image_source", "image_checked_at",
]


def list_wines(q: str | None = None, wine_type: str | None = None) -> list[dict]:
    sql = "SELECT * FROM wines"
    clauses, params = [], []
    if q:
        clauses.append("(name LIKE ? OR producer LIKE ? OR grape LIKE ? OR region LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if wine_type and wine_type != "all":
        clauses.append("type = ?")
        params.append(wine_type)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY tasted_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_wine(wine_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM wines WHERE id = ?", (wine_id,)).fetchone()
    return dict(row) if row else None


def create_wine(data: dict) -> dict:
    fields = [f for f in WINE_FIELDS if f in data]
    placeholders = ", ".join("?" for _ in fields)
    columns = ", ".join(fields)
    values = [data.get(f) for f in fields]
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO wines ({columns}) VALUES ({placeholders})", values
        )
        new_id = cur.lastrowid
    return get_wine(new_id)


def update_wine(wine_id: int, data: dict) -> dict | None:
    fields = [f for f in WINE_FIELDS if f in data]
    if not fields:
        return get_wine(wine_id)
    assignments = ", ".join(f"{f} = ?" for f in fields)
    values = [data.get(f) for f in fields] + [wine_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE wines SET {assignments} WHERE id = ?", values)
    return get_wine(wine_id)


def delete_wine(wine_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM wines WHERE id = ?", (wine_id,))
    return cur.rowcount > 0
