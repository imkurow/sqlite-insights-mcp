"""Launch the server over stdio exactly like Claude does, then call every tool."""

import json
import sys
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent


def show(label: str, result) -> None:
    status = "ERROR" if result.is_error else "ok"
    payload = result.structured_content if result.structured_content is not None else result.content[0].text
    print(f"[{status}] {label}\n{json.dumps(payload, indent=2)[:600]}\n")


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")], cwd=ROOT)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        info = await session.initialize()
        print(f"Connected to {info.server_info.name} v{info.server_info.version}\n")

        tools = (await session.list_tools()).tools
        print("Tools:", ", ".join(f"{t.name} (read-only={t.annotations.read_only_hint})" for t in tools), "\n")

        show("list_tables", await session.call_tool("list_tables", {}))
        show("describe_table customers", await session.call_tool("describe_table", {"table": "customers"}))
        show(
            "run_query: top 5 customers by revenue, last 90 days",
            await session.call_tool(
                "run_query",
                {
                    "sql": (
                        "SELECT c.company, ROUND(SUM(i.amount), 2) AS revenue "
                        "FROM invoices i JOIN orders o ON o.id = i.order_id "
                        "JOIN customers c ON c.id = o.customer_id "
                        "WHERE o.order_date >= date('now', '-90 days') "
                        "GROUP BY c.id ORDER BY revenue DESC LIMIT 5"
                    )
                },
            ),
        )
        blocked = await session.call_tool("run_query", {"sql": "DROP TABLE customers"})
        show("run_query: DROP TABLE customers (must be blocked)", blocked)

        schema = await session.read_resource("schema://database")
        print(f"[ok] schema://database resource: {len(schema.contents[0].text)} chars\n")

        if not blocked.is_error:
            raise SystemExit("FAIL: write was not blocked")
        print("Smoke test passed.")


if __name__ == "__main__":
    anyio.run(main)
