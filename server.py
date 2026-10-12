"""SQLite Insights: an MCP server that lets Claude answer business questions from a SQLite database, read-only."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations

from db import DEFAULT_MAX_ROWS, HARD_MAX_ROWS, QueryError, ReadOnlyDatabase

mcp = MCPServer(
    name="sqlite-insights",
    title="SQLite Insights",
    version="1.0.0",
    instructions=(
        "Read-only access to a sales database. Start with list_tables, use describe_table to learn "
        "columns and relationships, then answer questions with run_query (SQLite SELECT syntax). "
        "Revenue = SUM(invoices.amount); cancelled orders have no invoice. Dates are ISO text (YYYY-MM-DD)."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


@mcp.tool(annotations=READ_ONLY)
def list_tables() -> dict[str, Any]:
    """List every table in the database with its row count."""
    try:
        return {"tables": ReadOnlyDatabase().list_tables()}
    except QueryError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def describe_table(table: str) -> dict[str, Any]:
    """Show a table's columns, types, foreign keys and 3 sample rows."""
    try:
        return ReadOnlyDatabase().describe_table(table)
    except QueryError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
def run_query(sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> dict[str, Any]:
    """Run one read-only SQLite SELECT (or WITH ... SELECT) query and return the rows.

    Writes, schema changes, ATTACH and settings PRAGMAs are refused by the database itself.
    max_rows caps the result (default 200, maximum 1000); `truncated` says whether rows were cut off.
    """
    if not 1 <= max_rows <= HARD_MAX_ROWS:
        raise ToolError(f"max_rows must be between 1 and {HARD_MAX_ROWS}.")
    try:
        return ReadOnlyDatabase().run_query(sql, max_rows=max_rows)
    except QueryError as exc:
        raise ToolError(str(exc)) from exc


@mcp.resource("schema://database", name="database-schema", title="Database schema", mime_type="text/plain")
def database_schema() -> str:
    """The CREATE statements for every table and index."""
    try:
        return ReadOnlyDatabase().schema_sql()
    except QueryError as exc:
        raise ResourceError(str(exc)) from exc


if __name__ == "__main__":
    mcp.run()
