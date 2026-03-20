import asyncio
import atexit
import logging
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text

from app.models import DBType
from app.services.llm import json_default

logger = logging.getLogger(__name__)

DB_QUERY_TIMEOUT_SECONDS = 30
MAX_SCHEMA_CHARS = 12_000
MAX_RESULT_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_RESULT_ROWS = 10_000


def _sa_url(db_type: DBType, connection_string: str) -> str:
    """Convert a user-supplied connection string to a SQLAlchemy URL."""
    if db_type == DBType.mysql:
        if connection_string.startswith("mysql://"):
            return "mysql+pymysql://" + connection_string[len("mysql://"):]
        return connection_string
    if db_type == DBType.postgres:
        if connection_string.startswith("postgres://"):
            return "postgresql+psycopg2://" + connection_string[len("postgres://"):]
        if connection_string.startswith("postgresql://"):
            return "postgresql+psycopg2://" + connection_string[len("postgresql://"):]
        return connection_string
    if db_type == DBType.mssql:
        if connection_string.startswith("mssql://"):
            return "mssql+pymssql://" + connection_string[len("mssql://"):]
        return connection_string
    # SQLite: connection_string is already a valid SQLAlchemy URL (sqlite:///...)
    return connection_string


_engine_registry: list = []


@lru_cache(maxsize=32)
def _get_engine(url: str):
    engine = create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2)
    _engine_registry.append(engine)
    return engine


def _dispose_all_engines():
    for engine in _engine_registry:
        try:
            engine.dispose()
        except Exception:
            pass
    _engine_registry.clear()
    _get_engine.cache_clear()


atexit.register(_dispose_all_engines)


def _run_sql_sync(url: str, sql: str) -> list[dict[str, Any]]:
    engine = _get_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        rows: list[dict[str, Any]] = []
        for row in result:
            rows.append(
                {k.lower(): json_default(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
                 for k, v in row._mapping.items()}
            )
            if len(rows) >= MAX_RESULT_ROWS:
                logger.warning("Row limit reached (%d), truncating result set", MAX_RESULT_ROWS)
                break
        return rows


async def _run_sql(
    db_type: DBType, connection_string: str, sql: str
) -> list[dict[str, Any]]:
    url = _sa_url(db_type, connection_string)
    loop = asyncio.get_running_loop()
    async with asyncio.timeout(DB_QUERY_TIMEOUT_SECONDS):
        return await loop.run_in_executor(None, _run_sql_sync, url, sql)


_SCHEMA_INTROSPECTION_SQL: dict[DBType, str] = {
    DBType.postgres: """\
SELECT table_schema, table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name, ordinal_position
""",
    DBType.mysql: """\
SELECT table_schema, table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
ORDER BY table_schema, table_name, ordinal_position
""",
    DBType.mssql: """\
SELECT TABLE_SCHEMA as table_schema, TABLE_NAME as table_name,
       COLUMN_NAME as column_name, DATA_TYPE as data_type, IS_NULLABLE as is_nullable
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA')
ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
""",
    DBType.sqlite: """\
SELECT NULL as table_schema, m.name as table_name,
       p.name as column_name, p.type as data_type,
       CASE p."notnull" WHEN 1 THEN 'NO' ELSE 'YES' END as is_nullable
FROM sqlite_master m
JOIN pragma_table_info(m.name) p
WHERE m.type = 'table'
ORDER BY m.name, p.cid
""",
}


def _format_schema_rows(rows: list[dict]) -> str:
    """Convert information_schema rows into a readable schema string."""
    tables: dict[str, list[str]] = {}
    for row in rows:
        schema = row.get("table_schema")
        table = row.get("table_name", "?")
        key = f"{schema}.{table}" if schema else table
        col = row.get("column_name", "?")
        dtype = row.get("data_type", "?")
        nullable = row.get("is_nullable", "YES")
        tables.setdefault(key, []).append(
            f"  {col} {dtype}{',' if nullable == 'YES' else ' NOT NULL,'}"
        )
    lines = []
    for table, cols in tables.items():
        lines.append(f"Table: {table}")
        lines.extend(cols)
        lines.append("")
    return "\n".join(lines)


async def get_schema(db_type: DBType, connection_string: str) -> str:
    """Connect to the database and retrieve its schema."""
    introspection_sql = _SCHEMA_INTROSPECTION_SQL.get(db_type)
    if not introspection_sql:
        raise ValueError(f"Schema introspection not supported for {db_type.value}")

    rows = await _run_sql(db_type, connection_string, introspection_sql)
    schema = _format_schema_rows(rows)

    if len(schema) > MAX_SCHEMA_CHARS:
        truncated = schema[:MAX_SCHEMA_CHARS].rsplit("\n", 1)[0]
        logger.warning(
            "Schema truncated from %d to %d chars", len(schema), len(truncated)
        )
        schema = truncated + "\n\n[NOTE: Schema was truncated due to size. Some tables may be missing.]"

    return schema


async def run_query(
    db_type: DBType, connection_string: str, sql: str
) -> list[dict[str, Any]]:
    """Execute a SQL query and return the rows."""
    rows = await _run_sql(db_type, connection_string, sql)

    import json
    raw = json.dumps(rows)
    if len(raw.encode()) > MAX_RESULT_BYTES:
        logger.warning(
            "Query result exceeds size limit (%d bytes), discarding", len(raw.encode())
        )
        return [{"_error": "Result too large to process"}]

    return rows
