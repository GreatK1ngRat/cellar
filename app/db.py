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
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT NOT NULL,
    producer             TEXT,
    type                 TEXT NOT NULL,
    vintage              TEXT,
    region               TEXT,
    grape                TEXT,
    price                TEXT,
    rating               REAL,
    tasted_at            TEXT,
    where_tasted         TEXT,
    source               TEXT,
    notes                TEXT,
    image_url            TEXT,
    image_source         TEXT,
    image_checked_at     TEXT,
    added_by             TEXT,
    marked_for_deletion  INTEGER NOT NULL DEFAULT 0,
    marked_by            TEXT,
    marked_at            TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_wines_type ON wines(type);
CREATE INDEX IF NOT EXISTS idx_wines_tasted_at ON wines(tasted_at);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_wines_columns(conn)


def _migrate_wines_columns(conn) -> None:
    """Adds columns to an existing wines table that predates them.

    CREATE TABLE IF NOT EXISTS only creates a table that doesn't exist yet
    -- it does nothing to a table that already exists but is missing a
    newer column, which is exactly the situation for anyone upgrading from
    before user accounts existed. SQLite has no "ADD COLUMN IF NOT EXISTS",
    so this checks what's actually there first.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(wines)")}
    additions = {
        "added_by": "TEXT",
        "marked_for_deletion": "INTEGER NOT NULL DEFAULT 0",
        "marked_by": "TEXT",
        "marked_at": "TEXT",
    }
    for column, coltype in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE wines ADD COLUMN {column} {coltype}")


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
    "image_url", "image_source", "image_checked_at", "added_by",
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


def mark_wine_for_deletion(wine_id: int, username: str) -> dict | None:
    """A non-admin's stand-in for delete: flags the wine for an admin to
    remove, rather than removing it directly."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE wines SET marked_for_deletion = 1, marked_by = ?, "
            "marked_at = datetime('now') WHERE id = ?",
            (username, wine_id),
        )
    return get_wine(wine_id)


def unmark_wine(wine_id: int) -> dict | None:
    """Undoes a mark -- available to whoever marked it, or an admin."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE wines SET marked_for_deletion = 0, marked_by = NULL, "
            "marked_at = NULL WHERE id = ?",
            (wine_id,),
        )
    return get_wine(wine_id)


# ---- users -----------------------------------------------------------------

def list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def create_user(username: str, password_hash: str, role: str = "member") -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        new_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, username, role, created_at FROM users WHERE id = ?", (new_id,)
        ).fetchone()
    return dict(row)


def delete_user(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cur.rowcount > 0
