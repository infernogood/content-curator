import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from config import (
    ADMIN_IDS,
    DB_PATH,
    DEFAULT_SETTINGS,
    MEDIA_TYPE_TEXT,
    POST_STATUS_APPROVED,
    POST_STATUS_DRAFT,
    USER_STATUS_ACTIVE,
    USER_STATUS_BLOCKED,
    USER_STATUS_PENDING,
    ensure_runtime_dirs,
)

DATETIME_ISO = "%Y-%m-%d %H:%M:%S"


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    """Соединение с БД: коммит при успехе, rollback при ошибке, гарантированное закрытие."""
    ensure_runtime_dirs()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    """Текущее время в UTC (ISO-строка, сравнение работает лексикографически)."""
    return datetime.now(timezone.utc).strftime(DATETIME_ISO)


_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER NOT NULL UNIQUE,
    username      TEXT NOT NULL DEFAULT '',
    full_name     TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '{USER_STATUS_PENDING}',
    is_super_admin INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL = системный
    key         TEXT NOT NULL,
    value       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_settings_owner_key ON settings(owner_id, key)
    WHERE owner_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_settings_system_key ON settings(key)
    WHERE owner_id IS NULL;

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,              -- rss
    identifier      TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    extra           TEXT NOT NULL DEFAULT '{{}}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_owner ON sources(owner_id);

CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id       INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    source_url      TEXT NOT NULL DEFAULT '',
    dedup_hash      TEXT NOT NULL,
    raw_text        TEXT NOT NULL DEFAULT '',
    translated_text TEXT NOT NULL DEFAULT '',
    media_file_id   TEXT,
    media_type      TEXT NOT NULL DEFAULT '{MEDIA_TYPE_TEXT}',
    rating          INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT '{POST_STATUS_DRAFT}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    published_at    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_posts_owner_dedup ON posts(owner_id, dedup_hash);
"""


def init_db() -> None:
    """Создаёт таблицы, засевает системные дефолты Settings и супер-админов."""
    with _session() as conn:
        conn.executescript(_SCHEMA)

        for key, value in DEFAULT_SETTINGS.items():
            row = conn.execute(
                "SELECT 1 FROM settings WHERE owner_id IS NULL AND key = ?", (key,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO settings (owner_id, key, value, description) VALUES (NULL, ?, ?, '')",
                    (key, value),
                )

    for tg_id in ADMIN_IDS:
        upsert_user(telegram_id=tg_id, is_super_admin=True)


def upsert_user(
    telegram_id: int,
    username: str = "",
    full_name: str = "",
    is_super_admin: bool = False,
) -> dict:
    with _session() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()

        if row is None:
            status = USER_STATUS_ACTIVE if is_super_admin else USER_STATUS_PENDING
            cur = conn.execute(
                "INSERT INTO users (telegram_id, username, full_name, status, is_super_admin)"
                " VALUES (?, ?, ?, ?, ?)",
                (telegram_id, username, full_name, status, int(is_super_admin)),
            )
        else:
            conn.execute(
                "UPDATE users SET username = ?, full_name = ? WHERE id = ?",
                (username or row["username"], full_name or row["full_name"], row["id"]),
            )
            if is_super_admin:
                conn.execute(
                    "UPDATE users SET is_super_admin = 1, status = ? WHERE id = ?",
                    (USER_STATUS_ACTIVE, row["id"]),
                )
            cur = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],))
            return dict(cur.fetchone())

        cur = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,))
        return dict(cur.fetchone())


def get_user(user_id: int) -> dict | None:
    with _session() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def set_user_status(user_id: int, status: str) -> bool:
    with _session() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        if row["is_super_admin"] and status == USER_STATUS_BLOCKED:
            return False
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        return True


def count_users() -> int:
    with _session() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()
        return int(row["total"])


def list_users() -> list[dict]:
    with _session() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def list_pending_users() -> list[dict]:
    with _session() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = ? ORDER BY created_at DESC",
            (USER_STATUS_PENDING,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_active_users() -> list[dict]:
    with _session() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = ? ORDER BY id",
            (USER_STATUS_ACTIVE,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_effective(owner_id: int, key: str, default: str = "") -> str:
    with _session() as conn:
        row = conn.execute(
            "SELECT value FROM settings"
            " WHERE (owner_id = ? OR owner_id IS NULL) AND key = ?"
            " ORDER BY owner_id DESC LIMIT 1",
            (owner_id, key),
        ).fetchone()
        return row["value"] if row else default


def get_effective_int(owner_id: int, key: str, default: int = 0) -> int:
    try:
        return int(get_effective(owner_id, key, str(default)))
    except ValueError:
        return default


def set_setting(owner_id: int | None, key: str, value: str, description: str = "") -> None:
    with _session() as conn:
        row = conn.execute(
            "SELECT id FROM settings WHERE owner_id IS ? AND key = ?",
            (owner_id, key),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO settings (owner_id, key, value, description) VALUES (?, ?, ?, ?)",
                (owner_id, key, value, description),
            )
        else:
            conn.execute(
                "UPDATE settings SET value = ?, description = COALESCE(NULLIF(?, ''), description)"
                " WHERE id = ?",
                (value, description, row["id"]),
            )


def add_source(
    owner_id: int, type_: str, identifier: str, title: str = "",
) -> int:
    with _session() as conn:
        cur = conn.execute(
            "INSERT INTO sources (owner_id, type, identifier, title) VALUES (?, ?, ?, ?)",
            (owner_id, type_, identifier.strip(), title.strip()),
        )
        return int(cur.lastrowid)


def get_source(owner_id: int, source_id: int) -> dict | None:
    with _session() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND owner_id = ?", (source_id, owner_id)
        ).fetchone()
        return dict(row) if row else None


def list_sources(owner_id: int) -> list[dict]:
    with _session() as conn:
        rows = conn.execute(
            "SELECT * FROM sources WHERE owner_id = ? ORDER BY type, identifier",
            (owner_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_active_sources(owner_id: int) -> list[dict]:
    with _session() as conn:
        rows = conn.execute(
            "SELECT * FROM sources WHERE owner_id = ? AND enabled = 1",
            (owner_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def toggle_source(owner_id: int, source_id: int) -> bool | None:
    with _session() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND owner_id = ?", (source_id, owner_id)
        ).fetchone()
        if row is None:
            return None
        new_state = 0 if row["enabled"] else 1
        conn.execute("UPDATE sources SET enabled = ? WHERE id = ?", (new_state, source_id))
        return bool(new_state)


def delete_source(owner_id: int, source_id: int) -> bool:
    with _session() as conn:
        cur = conn.execute(
            "DELETE FROM sources WHERE id = ? AND owner_id = ?", (source_id, owner_id)
        )
        return cur.rowcount > 0


def mark_fetched(owner_id: int, source_id: int) -> None:
    with _session() as conn:
        conn.execute(
            "UPDATE sources SET last_fetched_at = ? WHERE id = ? AND owner_id = ?",
            (_now(), source_id, owner_id),
        )


def make_dedup_hash(source_url: str, raw_text: str) -> str:
    hash_seed = (source_url + "|" + raw_text).encode("utf-8")
    return hashlib.sha256(hash_seed).hexdigest()


def create_post(
    *,
    owner_id: int,
    source_id: int | None,
    source_url: str,
    raw_text: str,
    translated_text: str = "",
    media_file_id: str | None = None,
    media_type: str = MEDIA_TYPE_TEXT,
    rating: int = 0,
    dedup_hash: str | None = None,
    status: str = POST_STATUS_DRAFT,
) -> dict:
    if dedup_hash is None:
        dedup_hash = make_dedup_hash(source_url, raw_text)
    with _session() as conn:
        cur = conn.execute(
            "INSERT INTO posts (owner_id, source_id, source_url, dedup_hash, raw_text,"
            " translated_text, media_file_id, media_type, rating, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, source_id, source_url, dedup_hash, raw_text, translated_text,
             media_file_id, media_type, rating, status),
        )
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def exists_by_hash(owner_id: int, dedup_hash: str) -> bool:
    with _session() as conn:
        row = conn.execute(
            "SELECT 1 FROM posts WHERE owner_id = ? AND dedup_hash = ? LIMIT 1",
            (owner_id, dedup_hash),
        ).fetchone()
        return row is not None


def get_post(owner_id: int, post_id: int) -> dict | None:
    with _session() as conn:
        row = conn.execute(
            "SELECT * FROM posts WHERE id = ? AND owner_id = ?", (post_id, owner_id)
        ).fetchone()
        return dict(row) if row else None


def list_by_status(
    owner_id: int, status: str, limit: int = 20, offset: int = 0,
) -> list[dict]:
    with _session() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE owner_id = ? AND status = ?"
            " ORDER BY rating DESC, created_at DESC LIMIT ? OFFSET ?",
            (owner_id, status, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_by_status(owner_id: int, status: str) -> int:
    with _session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM posts WHERE owner_id = ? AND status = ?",
            (owner_id, status),
        ).fetchone()
        return int(row["total"])


def list_best(owner_id: int, limit: int = 10) -> list[dict]:
    with _session() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE owner_id = ? ORDER BY rating DESC, created_at DESC LIMIT ?",
            (owner_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def update_post_status(
    owner_id: int, post_id: int, status: str, set_published_at: bool = False,
) -> None:
    with _session() as conn:
        if set_published_at or status == POST_STATUS_APPROVED:
            conn.execute(
                "UPDATE posts SET status = ?, published_at = ? WHERE id = ? AND owner_id = ?",
                (status, _now(), post_id, owner_id),
            )
        else:
            conn.execute(
                "UPDATE posts SET status = ? WHERE id = ? AND owner_id = ?",
                (status, post_id, owner_id),
            )


def set_media_file_id(owner_id: int, post_id: int, file_id: str) -> None:
    with _session() as conn:
        conn.execute(
            "UPDATE posts SET media_file_id = ? WHERE id = ? AND owner_id = ?",
            (file_id, post_id, owner_id),
        )