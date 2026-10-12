import sqlite3

import pytest

from db import HARD_MAX_ROWS, QueryError, ReadOnlyDatabase, ReadOnlyViolation

TOP_CUSTOMERS_Q3 = """
SELECT c.company, ROUND(SUM(i.amount), 2) AS revenue
FROM invoices i
JOIN orders o ON o.id = i.order_id
JOIN customers c ON c.id = o.customer_id
WHERE o.order_date >= '2026-07-01' AND o.order_date < '2026-10-01'
GROUP BY c.id
ORDER BY revenue DESC, c.company
LIMIT 5
"""


def _counts(path):
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def test_list_tables_returns_all_tables_with_counts(sample_db):
    tables = {t["table"]: t["row_count"] for t in ReadOnlyDatabase().list_tables()}
    assert set(tables) == {"customers", "products", "orders", "order_items", "invoices"}
    assert tables == {k: v for k, v in _counts(sample_db).items() if k in tables}
    assert tables["customers"] == 40
    assert tables["orders"] == 170


def test_seed_data_is_unambiguous_for_demos(sample_db):
    rows = ReadOnlyDatabase().run_query("SELECT COUNT(*), COUNT(DISTINCT company) FROM customers")["rows"]
    assert rows == [[40, 40]]


def test_describe_table_shows_columns_and_foreign_keys(sample_db):
    info = ReadOnlyDatabase().describe_table("orders")
    assert [c["name"] for c in info["columns"]] == ["id", "customer_id", "order_date", "status"]
    assert info["foreign_keys"] == [{"column": "customer_id", "references": "customers.id"}]
    assert len(info["sample_rows"]["rows"]) == 3


def test_describe_unknown_table_lists_available_tables(sample_db):
    with pytest.raises(QueryError, match="Unknown table 'nope'.*customers"):
        ReadOnlyDatabase().describe_table("nope")


def test_run_query_matches_direct_sqlite(sample_db):
    expected = sqlite3.connect(sample_db).execute(TOP_CUSTOMERS_Q3).fetchall()
    result = ReadOnlyDatabase().run_query(TOP_CUSTOMERS_Q3)
    assert result["columns"] == ["company", "revenue"]
    assert [tuple(r) for r in result["rows"]] == expected
    assert len(expected) == 5
    assert result["truncated"] is False


def test_run_query_caps_rows_and_flags_truncation(sample_db):
    result = ReadOnlyDatabase().run_query("SELECT * FROM order_items", max_rows=10)
    assert result["row_count"] == 10
    assert result["truncated"] is True
    assert ReadOnlyDatabase().run_query("SELECT 1", max_rows=10**6)["max_rows"] == HARD_MAX_ROWS


def test_recursive_cte_is_allowed(sample_db):
    sql = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 5) SELECT SUM(x) FROM n"
    assert ReadOnlyDatabase().run_query(sql)["rows"] == [[15]]


@pytest.mark.parametrize(
    ("sql", "action"),
    [
        ("INSERT INTO customers (name) VALUES ('Mallory')", "INSERT on customers"),
        ("UPDATE products SET unit_price = 0", "UPDATE on products"),
        ("DELETE FROM invoices", "DELETE on invoices"),
        ("DROP TABLE orders", "schema change"),
        ("CREATE TABLE stolen (x)", "schema change"),
        ("ALTER TABLE customers ADD COLUMN notes TEXT", "ALTER TABLE"),
        ("ATTACH DATABASE 'other.db' AS other", "ATTACH"),
        ("PRAGMA journal_mode = DELETE", "PRAGMA journal_mode"),
        ("BEGIN", "TRANSACTION"),
        ("REPLACE INTO products (id, sku, name, category, unit_price) VALUES (1, 'x', 'x', 'x', 1)", "INSERT on products"),
    ],
)
def test_writes_are_refused_and_database_is_unchanged(sample_db, sql, action):
    before = _counts(sample_db)
    with pytest.raises(ReadOnlyViolation, match=action):
        ReadOnlyDatabase().run_query(sql)
    assert _counts(sample_db) == before


def test_multiple_statements_are_rejected(sample_db):
    with pytest.raises(QueryError, match="one SQL statement"):
        ReadOnlyDatabase().run_query("SELECT 1; DELETE FROM orders")


def test_empty_query_is_rejected(sample_db):
    with pytest.raises(QueryError, match="empty"):
        ReadOnlyDatabase().run_query("   ")


def test_missing_database_gives_setup_hint(tmp_path):
    with pytest.raises(QueryError, match="seed.py"):
        ReadOnlyDatabase(tmp_path / "missing.db").list_tables()


def test_runaway_query_is_stopped(sample_db, monkeypatch):
    monkeypatch.setattr("db.QUERY_TIMEOUT_SECONDS", 0.2)
    sql = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT COUNT(*) FROM n"
    with pytest.raises(QueryError, match="limit"):
        ReadOnlyDatabase().run_query(sql)
