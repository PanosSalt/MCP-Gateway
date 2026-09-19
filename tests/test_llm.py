import datetime
import decimal
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.llm import (
    MAX_QUESTION_CHARS,
    _extract_text,
    _get_client,
    assert_safe_select,
    generate_sql,
    json_default,
    summarize_results,
)

# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_client_raises_when_no_api_key():
    import app.services.llm as llm_mod

    llm_mod._client = None
    with patch("app.services.llm.get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(anthropic_api_key="")
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
            await _get_client()


@pytest.mark.asyncio
async def test_get_client_returns_cached_instance():
    import app.services.llm as llm_mod

    llm_mod._client = None
    with patch("app.services.llm.get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(
            anthropic_api_key="sk-ant-test"
        )
        c1 = await _get_client()
        c2 = await _get_client()
        assert c1 is c2
    llm_mod._client = None


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

def test_extract_text_returns_stripped_text():
    msg = SimpleNamespace(content=[SimpleNamespace(text="  hello  ")])
    assert _extract_text(msg) == "hello"


def test_extract_text_skips_non_text_blocks():
    msg = SimpleNamespace(
        content=[
            SimpleNamespace(thinking="internal"),
            SimpleNamespace(text="  answer  "),
        ]
    )
    assert _extract_text(msg) == "answer"


def test_extract_text_raises_on_empty_content():
    msg = SimpleNamespace(content=[], stop_reason="end_turn")
    with pytest.raises(RuntimeError, match="no text content"):
        _extract_text(msg)


def test_extract_text_raises_when_no_text_block():
    msg = SimpleNamespace(content=[SimpleNamespace(image="data")], stop_reason="end_turn")
    with pytest.raises(RuntimeError, match="no text content"):
        _extract_text(msg)


# ---------------------------------------------------------------------------
# assert_safe_select
# ---------------------------------------------------------------------------

def test_assert_safe_select_accepts_simple_select():
    assert_safe_select("SELECT id, name FROM users WHERE id = 1")


def test_assert_safe_select_accepts_select_with_join():
    assert_safe_select(
        "SELECT u.id FROM users u JOIN orders o ON u.id = o.user_id"
    )


def test_assert_safe_select_rejects_insert():
    with pytest.raises(ValueError, match="Non-SELECT"):
        assert_safe_select("INSERT INTO users (name) VALUES ('x')")


def test_assert_safe_select_rejects_drop():
    with pytest.raises(ValueError, match="Non-SELECT"):
        assert_safe_select("DROP TABLE users")


def test_assert_safe_select_rejects_multi_statement():
    with pytest.raises(ValueError, match="Non-SELECT"):
        assert_safe_select("SELECT 1; DROP TABLE users")


def test_assert_safe_select_rejects_empty():
    with pytest.raises(ValueError, match="empty after parsing"):
        assert_safe_select("")


def test_assert_safe_select_rejects_cte_with_delete():
    with pytest.raises(ValueError, match="Forbidden operation"):
        assert_safe_select(
            "WITH deleted AS (DELETE FROM users RETURNING id) "
            "SELECT * FROM deleted"
        )


def test_assert_safe_select_rejects_cte_with_insert():
    with pytest.raises(ValueError, match="Forbidden operation"):
        assert_safe_select(
            "WITH ins AS (INSERT INTO t VALUES (1) RETURNING id) "
            "SELECT * FROM ins"
        )


def test_assert_safe_select_rejects_update():
    with pytest.raises(ValueError, match="Non-SELECT"):
        assert_safe_select("UPDATE users SET name = 'x' WHERE id = 1")


def test_assert_safe_select_with_postgres_dialect():
    assert_safe_select(
        "SELECT name::text FROM users", db_type="postgres"
    )


def test_assert_safe_select_with_mysql_dialect():
    assert_safe_select(
        "SELECT `name` FROM `users`", db_type="mysql"
    )


def test_assert_safe_select_with_sqlite_dialect():
    assert_safe_select(
        "SELECT name FROM users LIMIT 1", db_type="sqlite"
    )


def test_assert_safe_select_with_mssql_dialect():
    assert_safe_select(
        "SELECT TOP 1 [name] FROM [users]", db_type="mssql"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (id INT)",
        "CREATE VIEW v AS SELECT 1",
        "ALTER TABLE users ADD COLUMN x INT",
        "TRUNCATE TABLE users",
    ],
)
def test_assert_safe_select_rejects_ddl(sql):
    """DDL nodes are declared forbidden; make sure each is actually caught."""
    with pytest.raises(ValueError, match="Non-SELECT|Forbidden operation"):
        assert_safe_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA table_info(users)",
        "ATTACH DATABASE '/tmp/evil.db' AS evil",
        "EXEC sp_who",
    ],
)
def test_assert_safe_select_rejects_command_nodes(sql):
    """Statements that are neither SELECT nor parseable must not get through.

    Which arm rejects them varies — ATTACH fails to parse, PRAGMA and EXEC
    parse to a Command node — but every one must raise.
    """
    with pytest.raises(
        ValueError, match="Non-SELECT|Forbidden operation|failed to parse",
    ):
        assert_safe_select(sql)


def test_assert_safe_select_rejects_unparseable_sql():
    with pytest.raises(ValueError, match="failed to parse"):
        assert_safe_select("SELECT FROM WHERE ((((")


# ---------------------------------------------------------------------------
# Async mock helper
# ---------------------------------------------------------------------------

def _mock_async_create(text: str) -> AsyncMock:
    """Return a mock _create_message that returns text."""
    msg = SimpleNamespace(content=[SimpleNamespace(text=text)])
    return AsyncMock(return_value=msg)


# ---------------------------------------------------------------------------
# generate_sql
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_sql_returns_stripped_sql():
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("  SELECT * FROM users  \n"),
    ):
        sql = await generate_sql(
            schema="CREATE TABLE users (id INT)",
            question="list all users",
            db_type="postgres",
        )
    assert sql == "SELECT * FROM users"


@pytest.mark.asyncio
async def test_generate_sql_returns_invalid_query():
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("INVALID_QUERY"),
    ):
        sql = await generate_sql(
            schema="CREATE TABLE orders (id INT)",
            question="what's the weather?",
            db_type="sqlite",
        )
    assert sql == "INVALID_QUERY"


@pytest.mark.asyncio
async def test_generate_sql_rejects_non_select():
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("DROP TABLE users"),
    ):
        with pytest.raises(ValueError, match="Non-SELECT"):
            await generate_sql(
                schema="CREATE TABLE users (id INT)",
                question="delete everything",
                db_type="postgres",
            )


@pytest.mark.asyncio
async def test_generate_sql_rejects_cte_mutation():
    with patch(
        "app.services.llm._create_message",
        _mock_async_create(
            "WITH d AS (DELETE FROM users RETURNING id) SELECT * FROM d"
        ),
    ):
        with pytest.raises(ValueError, match="Forbidden operation"):
            await generate_sql(
                schema="CREATE TABLE users (id INT)",
                question="delete everything sneakily",
                db_type="postgres",
            )


@pytest.mark.asyncio
async def test_generate_sql_truncates_long_question():
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("SELECT 1"),
    ) as mock_create:
        long_q = "x" * (MAX_QUESTION_CHARS + 500)
        await generate_sql(schema="t", question=long_q, db_type="postgres")
    call_kwargs = mock_create.call_args
    prompt_text = call_kwargs.kwargs["messages"][0]["content"]
    assert ("x" * (MAX_QUESTION_CHARS + 1)) not in prompt_text


@pytest.mark.asyncio
async def test_generate_sql_passes_json_schema_through():
    """str.format() handles braces in values correctly without escaping."""
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("SELECT 1"),
    ) as mock_create:
        await generate_sql(
            schema='{"default": 0}',
            question="count",
            db_type="postgres",
        )
    call_kwargs = mock_create.call_args
    prompt_text = call_kwargs.kwargs["messages"][0]["content"]
    assert '{"default": 0}' in prompt_text


@pytest.mark.asyncio
async def test_generate_sql_wraps_rate_limit_error():
    with patch(
        "app.services.llm._create_message",
        AsyncMock(
            side_effect=RuntimeError(
                "AI service rate limit reached — try again shortly."
            )
        ),
    ):
        with pytest.raises(RuntimeError, match="rate limit"):
            await generate_sql("s", "q", "postgres")


@pytest.mark.asyncio
async def test_generate_sql_wraps_connection_error():
    with patch(
        "app.services.llm._create_message",
        AsyncMock(side_effect=RuntimeError("Could not reach AI service.")),
    ):
        with pytest.raises(RuntimeError, match="Could not reach"):
            await generate_sql("s", "q", "postgres")


# ---------------------------------------------------------------------------
# summarize_results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summarize_results_returns_summary():
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("There are 42 users."),
    ):
        summary = await summarize_results(
            question="How many users?",
            sql="SELECT count(*) FROM users",
            results=[{"count": 42}],
        )
    assert summary == "There are 42 users."


@pytest.mark.asyncio
async def test_summarize_results_includes_total_row_count():
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("Many rows."),
    ) as mock_create:
        big_results = [{"id": i} for i in range(100)]
        await summarize_results(
            question="all?",
            sql="SELECT * FROM t",
            results=big_results,
        )
    call_kwargs = mock_create.call_args
    prompt_text = call_kwargs.kwargs["messages"][0]["content"]
    assert "100 total rows" in prompt_text
    assert "showing first 50" in prompt_text


@pytest.mark.asyncio
async def test_summarize_results_handles_db_types():
    """datetime, Decimal, UUID, bytes all serialize without error."""
    results = [
        {
            "ts": datetime.datetime(2025, 1, 1, 12, 0),
            "amount": decimal.Decimal("19.99"),
            "uid": uuid.UUID("12345678-1234-5678-1234-567812345678"),
            "data": b"\xde\xad",
        }
    ]
    with patch(
        "app.services.llm._create_message",
        _mock_async_create("Summary."),
    ) as mock_create:
        await summarize_results(
            question="show me",
            sql="SELECT * FROM t",
            results=results,
        )
    call_kwargs = mock_create.call_args
    prompt_text = call_kwargs.kwargs["messages"][0]["content"]
    assert "2025-01-01" in prompt_text
    assert "19.99" in prompt_text
    assert "12345678-1234-5678-1234-567812345678" in prompt_text
    assert "dead" in prompt_text


# ---------------------------------------------------------------------------
# json_default
# ---------------------------------------------------------------------------

def test_json_default_datetime():
    assert json_default(datetime.datetime(2025, 6, 15, 10, 30)) == "2025-06-15T10:30:00"


def test_json_default_date():
    assert json_default(datetime.date(2025, 6, 15)) == "2025-06-15"


def test_json_default_decimal():
    assert json_default(decimal.Decimal("3.14")) == "3.14"


def test_json_default_uuid():
    u = uuid.UUID("abcdef00-1234-5678-9abc-def012345678")
    assert json_default(u) == "abcdef00-1234-5678-9abc-def012345678"


def test_json_default_bytes():
    assert json_default(b"\xca\xfe") == "cafe"


def test_json_default_raises_on_unknown():
    with pytest.raises(TypeError, match="not JSON serializable"):
        json_default(object())
