"""Read-only access to a SQLite database, with write protection enforced by SQLite itself."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "sample.db"
DB_PATH_ENV = "SQLITE_INSIGHTS_DB"

DEFAULT_MAX_ROWS = 200
HARD_MAX_ROWS = 1000
QUERY_TIMEOUT_SECONDS = 5.0

_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}
_READ_ONLY_PRAGMAS = {"table_info", "table_xinfo", "table_list", "index_list", "index_info", "foreign_key_list"}
_SCHEMA_TABLES = {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}

_ACTION_NAMES = {
    getattr(sqlite3, f"SQLITE_{name}"): name.replace("_", " ")
    for name in (
        "CREATE_INDEX", "CREATE_TABLE", "CREATE_TEMP_INDEX", "CREATE_TEMP_TABLE",
        "CREATE_TEMP_TRIGGER", "CREATE_TEMP_VIEW", "CREATE_TRIGGER", "CREATE_VIEW",
        "DELETE", "DROP_INDEX", "DROP_TABLE", "DROP_TEMP_INDEX", "DROP_TEMP_TABLE",
        "DROP_TEMP_TRIGGER", "DROP_TEMP_VIEW", "DROP_TRIGGER", "DROP_VIEW", "INSERT",
        "PRAGMA", "TRANSACTION", "UPDATE", "ATTACH", "DETACH", "ALTER_TABLE",
        "REINDEX", "ANALYZE", "CREATE_VTABLE", "DROP_VTABLE", "SAVEPOINT",
    )
}


class QueryError(Exception):
    """A problem the caller can fix: bad SQL, unknown table, missing database."""


class ReadOnlyViolation(QueryError):
    """The statement tried to change the database."""


def resolve_db_path() -> Path:
    return Path(os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH)


class ReadOnlyDatabase:
    """Opens the database with mode=ro and an authorizer that only permits reads.

    Two independent layers: the file handle cannot write, and SQLite refuses to
    compile any statement that would write, attach another file, or change settings.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else resolve_db_path()
        self._denied: str | None = None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            raise QueryError(
                f"Database not found at {self.path}. Run `python seed.py` to create the sample database."
            )
        uri = self.path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None)
        try:
            conn.set_authorizer(self._authorize)
            deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            yield conn
        finally:
            conn.close()

    def _authorize(self, action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None) -> int:
        if action in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA and arg1 and arg1.lower() in _READ_ONLY_PRAGMAS:
            return sqlite3.SQLITE_OK
        self._denied = _describe_action(action, arg1)
        return sqlite3.SQLITE_DENY

    def _execute(self, sql: str, params: tuple[Any, ...] = (), max_rows: int = HARD_MAX_ROWS) -> dict[str, Any]:
        self._denied = None
        with self._connect() as conn:
            try:
                cursor = conn.execute(sql, params)
                fetched = cursor.fetchmany(max_rows + 1)
            except sqlite3.ProgrammingError as exc:
                if "one statement at a time" in str(exc):
                    raise QueryError("Only one SQL statement per call is allowed.") from exc
                raise QueryError(f"Invalid query: {exc}") from exc
            except sqlite3.DatabaseError as exc:
                raise self._translate(exc) from exc
            columns = [col[0] for col in cursor.description or []]
        rows = [[_jsonable(value) for value in row] for row in fetched[:max_rows]]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": len(fetched) > max_rows,
        }

    def _translate(self, exc: sqlite3.DatabaseError) -> QueryError:
        message = str(exc)
        if self._denied or "not authorized" in message or "readonly database" in message:
            action = self._denied or "a write"
            return ReadOnlyViolation(
                f"Blocked: this server is read-only, and the statement tried to perform {action}. "
                "Only SELECT queries are allowed."
            )
        if message == "interrupted":
            return QueryError(f"Query stopped: it ran longer than the {QUERY_TIMEOUT_SECONDS:g}s limit.")
        return QueryError(f"SQLite error: {message}")

    def list_tables(self) -> list[dict[str, Any]]:
        names = self._execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )["rows"]
        tables = []
        for (name,) in names:
            count = self._execute(f"SELECT COUNT(*) FROM {_quote(name)}")["rows"][0][0]
            tables.append({"table": name, "row_count": count})
        return tables

    def describe_table(self, table: str) -> dict[str, Any]:
        known = {t["table"] for t in self.list_tables()}
        if table not in known:
            raise QueryError(f"Unknown table '{table}'. Available tables: {', '.join(sorted(known))}.")
        columns = self._execute(
            'SELECT name, type, "notnull", dflt_value, pk FROM pragma_table_info(?)', (table,)
        )["rows"]
        foreign_keys = self._execute(
            'SELECT "from", "table", "to" FROM pragma_foreign_key_list(?)', (table,)
        )["rows"]
        sample = self._execute(f"SELECT * FROM {_quote(table)} LIMIT 3")
        return {
            "table": table,
            "columns": [
                {"name": n, "type": t, "nullable": not nn, "default": d, "primary_key": bool(pk)}
                for n, t, nn, d, pk in columns
            ],
            "foreign_keys": [{"column": f, "references": f"{rt}.{rc}"} for f, rt, rc in foreign_keys],
            "sample_rows": {"columns": sample["columns"], "rows": sample["rows"]},
        }

    def run_query(self, sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> dict[str, Any]:
        sql = sql.strip()
        if not sql:
            raise QueryError("The query is empty.")
        limit = max(1, min(int(max_rows), HARD_MAX_ROWS))
        result = self._execute(sql, max_rows=limit)
        result["max_rows"] = limit
        return result

    def schema_sql(self) -> str:
        rows = self._execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"
        )["rows"]
        return ";\n\n".join(row[0] for row in rows) + ";\n"


def _describe_action(action: int, arg1: str | None) -> str:
    name = _ACTION_NAMES.get(action, f"action {action}")
    # SQLite authorizes DDL as a write to the schema table before naming the DDL itself.
    if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and arg1 in _SCHEMA_TABLES:
        return "a schema change (CREATE/DROP)"
    if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and arg1:
        return f"{name} on {arg1}"
    if action == sqlite3.SQLITE_PRAGMA and arg1:
        return f"PRAGMA {arg1}"
    return name


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<blob {len(value)} bytes>"
    return value
