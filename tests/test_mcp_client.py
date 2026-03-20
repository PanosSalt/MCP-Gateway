"""Tests for app.services.mcp_client — SQLAlchemy-based schema + query."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import DBType
from app.services.mcp_client import (
    MAX_SCHEMA_CHARS,
    _format_schema_rows,
    _sa_url,
    get_schema,
    run_query,
)

# ---------------------------------------------------------------------------
# _sa_url
# ---------------------------------------------------------------------------


def test_sa_url_postgres():
    assert _sa_url(DBType.postgres, "postgresql://u:p@host/db") == "postgresql+psycopg2://u:p@host/db"


def test_sa_url_postgres_short_prefix():
    assert _sa_url(DBType.postgres, "postgres://u:p@host/db") == "postgresql+psycopg2://u:p@host/db"


def test_sa_url_mysql():
    assert _sa_url(DBType.mysql, "mysql://u:p@host/db") == "mysql+pymysql://u:p@host/db"


def test_sa_url_mssql():
    assert _sa_url(DBType.mssql, "mssql://u:p@host/db") == "mssql+pymssql://u:p@host/db"


def test_sa_url_sqlite():
    assert _sa_url(DBType.sqlite, "sqlite:///test.db") == "sqlite:///test.db"


# ---------------------------------------------------------------------------
# _format_schema_rows
# ---------------------------------------------------------------------------


def test_format_schema_rows_basic():
    rows = [
        {"table_schema": "public", "table_name": "users", "column_name": "id", "data_type": "integer", "is_nullable": "NO"},
        {"table_schema": "public", "table_name": "users", "column_name": "name", "data_type": "varchar", "is_nullable": "YES"},
    ]
    result = _format_schema_rows(rows)
    assert "Table: public.users" in result
    assert "id integer NOT NULL," in result
    assert "name varchar," in result


def test_format_schema_rows_no_schema():
    rows = [
        {"table_schema": None, "table_name": "items", "column_name": "id", "data_type": "int", "is_nullable": "NO"},
    ]
    result = _format_schema_rows(rows)
    assert "Table: items" in result


def test_format_schema_rows_empty():
    assert _format_schema_rows([]) == ""


# ---------------------------------------------------------------------------
# get_schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schema_returns_formatted_schema():
    mock_rows = [
        {"table_schema": "public", "table_name": "orders", "column_name": "id", "data_type": "int", "is_nullable": "NO"},
    ]
    with patch("app.services.mcp_client._run_sql", new_callable=AsyncMock, return_value=mock_rows):
        schema = await get_schema(DBType.postgres, "pg://host/db")
    assert "Table: public.orders" in schema
    assert "id int NOT NULL," in schema


@pytest.mark.asyncio
async def test_get_schema_truncates_large_schema():
    big_rows = [
        {"table_schema": "public", "table_name": f"table_{i}", "column_name": "col", "data_type": "text", "is_nullable": "YES"}
        for i in range(5000)
    ]
    with patch("app.services.mcp_client._run_sql", new_callable=AsyncMock, return_value=big_rows):
        schema = await get_schema(DBType.postgres, "pg://host/db")
    assert len(schema) <= MAX_SCHEMA_CHARS + 100
    assert schema.endswith("[NOTE: Schema was truncated due to size. Some tables may be missing.]")


# ---------------------------------------------------------------------------
# run_query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_query_returns_rows():
    mock_rows = [{"id": 1, "name": "Alice"}]
    with patch("app.services.mcp_client._run_sql", new_callable=AsyncMock, return_value=mock_rows):
        result = await run_query(DBType.postgres, "pg://host/db", "SELECT * FROM users")
    assert result == [{"id": 1, "name": "Alice"}]


@pytest.mark.asyncio
async def test_run_query_truncates_large_result():
    huge_rows = [{"data": "x" * 1_000_000} for _ in range(20)]
    with patch("app.services.mcp_client._run_sql", new_callable=AsyncMock, return_value=huge_rows):
        result = await run_query(DBType.postgres, "pg://host/db", "SELECT 1")
    assert result == [{"_error": "Result too large to process"}]
