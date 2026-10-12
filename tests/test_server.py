import pytest
from mcp import Client

from server import mcp

pytestmark = pytest.mark.anyio


async def test_tools_are_listed_and_marked_read_only(sample_db):
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"list_tables", "describe_table", "run_query"}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


async def test_run_query_returns_structured_rows(sample_db):
    async with Client(mcp) as client:
        result = await client.call_tool("run_query", {"sql": "SELECT COUNT(*) AS n FROM customers"})
    assert not result.is_error
    assert result.structured_content["rows"] == [[40]]


async def test_write_through_tool_returns_clear_error(sample_db):
    async with Client(mcp) as client:
        result = await client.call_tool("run_query", {"sql": "DELETE FROM orders"})
    assert result.is_error
    assert "read-only" in result.content[0].text


async def test_out_of_range_max_rows_is_rejected(sample_db):
    async with Client(mcp) as client:
        result = await client.call_tool("run_query", {"sql": "SELECT 1", "max_rows": 0})
    assert result.is_error
    assert "max_rows" in result.content[0].text


async def test_schema_resource_contains_create_statements(sample_db):
    async with Client(mcp) as client:
        result = await client.read_resource("schema://database")
    text = result.contents[0].text
    assert "CREATE TABLE customers" in text
    assert "CREATE TABLE invoices" in text
