import asyncio
import datetime
import decimal
import json
import logging
import uuid
from typing import Any

import anthropic
import anthropic.types
import httpx
import sqlglot
import sqlglot.errors
import sqlglot.expressions
from anthropic.types import MessageParam

from app.config import get_settings

logger = logging.getLogger(__name__)

SQL_GENERATION_PROMPT = """\
You are a SQL expert. Given the schema and question, \
generate a single safe SELECT query.

Database type: {db_type}
Schema: {schema}
Question: {question}

Rules:
- Only SELECT statements. Never INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE.
- Return ONLY the raw SQL, no explanation, no markdown, no backticks.
- If unanswerable with this schema, return: INVALID_QUERY"""

SUMMARIZATION_PROMPT = """\
User asked: "{question}"
SQL run: {sql}
Results ({total_rows} total rows, showing first {shown_rows}): {results}

Write a clear, concise natural language answer. Be direct. If empty, say so."""

MAX_QUESTION_CHARS = 2000  # must match QueryRequest.question max_length in schemas

_DIALECT_MAP: dict[str, str] = {
    "postgres": "postgres",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "mssql": "tsql",
}

_FORBIDDEN_NODES = (
    sqlglot.expressions.Insert,
    sqlglot.expressions.Update,
    sqlglot.expressions.Delete,
    sqlglot.expressions.Drop,
    sqlglot.expressions.Create,
    sqlglot.expressions.AlterTable,
    sqlglot.expressions.TruncateTable,
    sqlglot.expressions.Command,
)

_client: anthropic.AsyncAnthropic | None = None
_client_lock = asyncio.Lock()


async def _get_client() -> anthropic.AsyncAnthropic:
    """Return a cached async Anthropic client, creating it on first call."""
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                api_key = get_settings().anthropic_api_key
                if not api_key:
                    raise RuntimeError(
                        "ANTHROPIC_API_KEY is not set. "
                        "Configure it in .env or environment variables."
                    )
                _client = anthropic.AsyncAnthropic(
                    api_key=api_key,
                    timeout=httpx.Timeout(30.0),
                )
    return _client


async def _create_message(
    *,
    model: str,
    max_tokens: int,
    messages: list[MessageParam],
) -> anthropic.types.Message:
    """Call the Anthropic API with unified error handling."""
    try:
        client = await _get_client()
        return await client.messages.create(
            model=model, max_tokens=max_tokens, messages=messages
        )
    except anthropic.RateLimitError:
        raise RuntimeError(
            "AI service rate limit reached — try again shortly."
        ) from None
    except anthropic.APIConnectionError:
        raise RuntimeError("Could not reach AI service.") from None
    except anthropic.APIError as exc:
        raise RuntimeError(
            f"AI service error: {exc.status_code}"
        ) from None


def _extract_text(msg: anthropic.types.Message) -> str:
    """Extract the first text block from an Anthropic message."""
    for block in msg.content:
        if hasattr(block, "text"):
            return block.text.strip()
    raise RuntimeError(
        f"AI service returned no text content (stop_reason={msg.stop_reason!r})"
    )


def assert_safe_select(sql: str, db_type: str = "") -> None:
    """Validate that SQL contains only SELECT with no forbidden sub-nodes.

    Two-layer defence:
    - Top level: each statement must be a Select (catches standalone
      INSERT, UPDATE, DROP, TRUNCATE, etc.)
    - AST walk: find() scans inside each Select for forbidden nodes
      embedded in CTEs or subqueries.
    """
    dialect = _DIALECT_MAP.get(db_type, "")
    try:
        raw_statements = sqlglot.parse(sql, dialect=dialect or None)
    except sqlglot.errors.ParseError as exc:
        raise ValueError(
            f"Generated SQL failed to parse: {exc}"
        ) from exc

    # sqlglot.parse can return None entries (e.g. trailing semicolons)
    statements = [s for s in raw_statements if s is not None]

    if not statements:
        raise ValueError("Generated SQL is empty after parsing")

    for stmt in statements:
        if not isinstance(stmt, sqlglot.expressions.Select):
            raise ValueError(
                "Non-SELECT statement in generated SQL: "
                f"{type(stmt).__name__}"
            )
        found = stmt.find(*_FORBIDDEN_NODES)
        if found:
            raise ValueError(
                "Forbidden operation in SQL AST: "
                f"{type(found).__name__}"
            )


def json_default(obj: Any) -> Any:
    """Serialize types commonly returned by databases that json.dumps can't handle."""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.hex()
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )


async def generate_sql(schema: str, question: str, db_type: str) -> str:
    """Ask the LLM to produce a SELECT query from a natural language question."""
    settings = get_settings()
    question = question[:MAX_QUESTION_CHARS]
    prompt = SQL_GENERATION_PROMPT.format(
        db_type=db_type,
        schema=schema,
        question=question,
    )
    msg = await _create_message(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens_sql,
        messages=[{"role": "user", "content": prompt}],
    )
    sql = _extract_text(msg)
    if sql.upper() != "INVALID_QUERY":
        assert_safe_select(sql, db_type)
    return sql


async def summarize_results(
    question: str, sql: str, results: list[dict[str, Any]]
) -> str:
    """Summarize SQL query results in natural language."""
    settings = get_settings()
    question = question[:MAX_QUESTION_CHARS]
    shown = results[:50]
    prompt = SUMMARIZATION_PROMPT.format(
        question=question,
        sql=sql,
        total_rows=len(results),
        shown_rows=len(shown),
        results=json.dumps(shown, indent=2, default=json_default),
    )
    msg = await _create_message(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens_summary,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(msg)
