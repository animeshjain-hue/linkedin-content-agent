import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path("migrations")


@contextmanager
def get_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations(db_path: Path, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    for sql_file in sorted(migrations_dir.glob("*.sql")):
        with get_connection(db_path) as conn:
            already_applied = (
                _table_exists(conn, "schema_migrations")
                and conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE name = ?", (sql_file.name,)
                ).fetchone()
                is not None
            )
        if already_applied:
            continue
        # executescript commits implicitly — use a raw connection outside get_connection
        raw = sqlite3.connect(str(db_path))
        try:
            raw.executescript(sql_file.read_text())
            raw.execute(
                "INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)",
                (sql_file.name,),
            )
            raw.commit()
        finally:
            raw.close()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )
