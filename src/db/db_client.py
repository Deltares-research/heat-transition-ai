"""PostgreSQL client for the warmteprogramma knowledge graph.

Targets Azure Database for PostgreSQL (Flexible Server). The connection string
lives in ``secrets/db.env`` and is never hardcoded:

    DB_URL=postgresql://user:password@myserver.postgres.database.azure.com:5432/nplw?sslmode=require

Real environment variables win over the file, so CI and App Service settings
override it without editing anything.

Smoke-test the connection with::

    python -m src.db.db_client
"""

from __future__ import annotations

import argparse
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import psycopg2
from dotenv import load_dotenv
from psycopg2 import extensions, extras

from src.console import safe_console
from src.db.utils import clean, parse_response

__all__ = [
    "DBClient", "clean", "parse_response", "resolve_dsn", "load_registry",
    "table_counts", "main",
]


ROOT = Path(__file__).parents[2]
ENV_PATH = ROOT / "secrets" / "db.env"

SQL_DIR = Path(__file__).parent / "sql"
NODES_PATH = SQL_DIR / "nodes.sql"
EDGES_PATH = SQL_DIR / "edges.sql"
INSERTS_PATH = SQL_DIR / "inserts.sql"
QUERIES_PATH = SQL_DIR / "queries.sql"

# Applied only when the DSN does not already set them, so an explicit
# sslmode=verify-full in db.env is never silently downgraded.
#
# keepalives matter on Azure specifically: the platform load balancer drops
# connections idle for ~4 minutes, which otherwise surfaces mid-ingest as an
# unexplained "server closed the connection unexpectedly".
CONNECT_DEFAULTS = {
    "sslmode": "require",
    "connect_timeout": "10",
    "application_name": "heat-transition-ai",
    "keepalives": "1",
    "keepalives_idle": "30",
    "keepalives_interval": "10",
    "keepalives_count": "5",
}

CONNECT_RETRIES = 3

# A local development server usually has no TLS at all, and requiring it there
# fails with "server does not support SSL". Remote hosts keep sslmode=require.
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def connect_options(parsed: dict[str, str]) -> dict[str, str]:
    """Defaults to apply, minus anything the DSN already specifies."""
    defaults = dict(CONNECT_DEFAULTS)
    host = parsed.get("host", "")
    if host in LOCAL_HOSTS or host.startswith("/"):  # empty, loopback or socket
        defaults["sslmode"] = "prefer"
    return {k: v for k, v in defaults.items() if k not in parsed}

_MISSING_DSN = f"""No database connection string found.

Create {ENV_PATH} containing:

    DB_URL=postgresql://USER:PASSWORD@SERVER.postgres.database.azure.com:5432/nplw?sslmode=require

or set the discrete variables PGHOST, PGUSER, PGPASSWORD, PGDATABASE, PGPORT.
See secrets/db.env.example."""

_BAD_DSN_HINT = """If the password contains '@', ':', '/', '?' or '#', either
percent-encode it in the URL or use the discrete PGHOST / PGUSER / PGPASSWORD /
PGDATABASE variables instead, which need no escaping."""

_CONNECT_HINT = """Check, in this order:
  1. the server's firewall allows your client IP (Azure blocks all by default),
  2. the server name and database exist,
  3. the username and password are correct,
  4. the password in DB_URL is percent-encoded if it contains '@' or ':'."""


# ──────────────────────────────────────────────────────────────
# SQL registry
# ──────────────────────────────────────────────────────────────

_NAME_MARKER = "-- name: "
_META_RE = re.compile(r"--\s*(description|use when|params)\s*:\s*(.*)", re.I)
_PARAM_RE = re.compile(r"\$(\w+)")


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    """Parse a ``-- name:`` annotated .sql file into a statement registry.

    Each block becomes ``{description, use_when, query, params}``. Inserts carry
    empty metadata; queries use it to build their MCP tool descriptions.
    """
    registry: dict[str, dict[str, Any]] = {}

    for block in path.read_text(encoding="utf-8").split(_NAME_MARKER)[1:]:
        lines = block.splitlines()
        name = lines[0].strip()

        meta: dict[str, str] = {}
        body: list[str] = []

        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("--"):
                if body:  # a trailing comment belongs to the next block
                    continue
                match = _META_RE.match(stripped)
                if match:
                    key = match.group(1).lower().replace(" ", "_")
                    meta[key] = match.group(2).strip()
                continue
            if stripped:
                body.append(line)

        statement = "\n".join(body).strip().rstrip(";")
        if not statement:
            continue

        registry[name] = {
            "description": meta.get("description", ""),
            "use_when": meta.get("use_when", ""),
            "query": statement,
            "params": sorted(set(_PARAM_RE.findall(statement))),
        }

    return registry


# ──────────────────────────────────────────────────────────────
# Connection string
# ──────────────────────────────────────────────────────────────

def resolve_dsn(env_path: Path | str = ENV_PATH) -> str:
    """Connection string from the environment, falling back to secrets/db.env.

    ``load_dotenv`` does not override variables that are already set, so a real
    environment variable always beats the file.
    """
    load_dotenv(env_path)

    url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL")
    if url and url.strip():
        return url.strip()

    host = os.environ.get("PGHOST")
    if host:
        parts = {
            "host": host,
            "port": os.environ.get("PGPORT", "5432"),
            "dbname": os.environ.get("PGDATABASE", "nplw"),
            "user": os.environ.get("PGUSER"),
            "password": os.environ.get("PGPASSWORD"),
        }
        # make_dsn quotes values correctly, so no escaping burden on the caller.
        return extensions.make_dsn(**{k: v for k, v in parts.items() if v})

    raise RuntimeError(_MISSING_DSN)


def _parse_dsn(dsn: str) -> dict[str, str]:
    try:
        return extensions.parse_dsn(dsn)
    except psycopg2.ProgrammingError as exc:
        raise RuntimeError(f"Malformed connection string: {exc}\n\n{_BAD_DSN_HINT}") from exc


def describe_dsn(dsn: str) -> str:
    """Human-readable connection summary with the password removed."""
    try:
        parsed = _parse_dsn(dsn)
    except RuntimeError:
        return "<unparseable dsn>"
    shown = {k: v for k, v in parsed.items() if k != "password"}
    return " ".join(f"{k}={v}" for k, v in sorted(shown.items()))


# ──────────────────────────────────────────────────────────────
# Client
# ──────────────────────────────────────────────────────────────

class DBClient:
    """Thin psycopg2 wrapper around the knowledge-graph database.

    Transactions are explicit: writes accumulate until :meth:`commit`. If the
    connection drops while a transaction is open the client refuses to
    reconnect silently — see :meth:`ensure_connection`.
    """

    def __init__(
        self,
        readonly: bool = False,
        dsn: str | None = None,
        ensure_schema: bool = True,
        env_path: Path | str = ENV_PATH,
        connect_retries: int = CONNECT_RETRIES,
    ) -> None:
        self.readonly = readonly
        self.dsn = (dsn or resolve_dsn(env_path)).strip()
        self.connect_retries = connect_retries
        self.conn: psycopg2.extensions.connection | None = None

        self._schema_wanted = ensure_schema and not readonly
        self._schema_ready = False
        self._dirty = False  # uncommitted writes outstanding

        self.load_query_registry()
        self.connect()

    # ── connection lifecycle ──────────────────────────────────

    @property
    def safe_dsn(self) -> str:
        return describe_dsn(self.dsn)

    def connect(self) -> None:
        """Open the connection, retrying transient Azure failures."""
        if self.conn is not None and not self.conn.closed:
            return

        options = connect_options(_parse_dsn(self.dsn))

        for attempt in range(1, self.connect_retries + 1):
            try:
                self.conn = psycopg2.connect(self.dsn, **options)
                break
            except psycopg2.OperationalError as exc:
                if attempt == self.connect_retries:
                    raise ConnectionError(
                        f"Could not connect to {self.safe_dsn} after "
                        f"{self.connect_retries} attempts: {exc}\n\n{_CONNECT_HINT}"
                    ) from exc
                time.sleep(2 ** (attempt - 1))

        if self.readonly:
            self.conn.set_session(readonly=True, autocommit=True)
        elif self._schema_wanted and not self._schema_ready:
            self.ensure_schema()

    def ensure_connection(self) -> None:
        """Reconnect if the connection died — but never mid-transaction.

        Azure drops idle and failed-over connections. Reconnecting with writes
        outstanding would silently resume a half-applied transaction and then
        commit it as if it were whole, so that case raises instead.
        """
        if (
            self.conn is not None
            and not self.conn.closed
            and self.conn.get_transaction_status() != extensions.TRANSACTION_STATUS_UNKNOWN
        ):
            return

        if self._dirty:
            raise ConnectionError(
                "The connection dropped with uncommitted writes outstanding; that "
                "work is lost. Re-run the ingest - every insert is an UPSERT, so "
                "re-running is safe."
            )

        self._discard()
        self.connect()

    def _discard(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except psycopg2.Error:
                pass
        self.conn = None

    def close(self) -> None:
        self._discard()
        self._dirty = False

    def __enter__(self) -> "DBClient":
        self.ensure_connection()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── schema and registry ───────────────────────────────────

    def ensure_schema(self) -> None:
        """Create tables, indices and functions if absent. Idempotent."""
        with self.conn.cursor() as cur:
            cur.execute(NODES_PATH.read_text(encoding="utf-8"))
            cur.execute(EDGES_PATH.read_text(encoding="utf-8"))
        self.conn.commit()
        self._schema_ready = True

    def load_query_registry(self) -> None:
        self.inserts = load_registry(INSERTS_PATH)
        self.queries = load_registry(QUERIES_PATH)

    # ── transactions ──────────────────────────────────────────

    def commit(self) -> None:
        if self.conn is not None and not self.conn.closed:
            self.conn.commit()
        self._dirty = False

    def rollback(self) -> None:
        if self.conn is not None and not self.conn.closed:
            self.conn.rollback()
        self._dirty = False

    @contextmanager
    def transaction(self) -> Iterator["DBClient"]:
        """Commit on clean exit, roll back on any exception."""
        try:
            yield self
            self.commit()
        except Exception:
            self.rollback()
            raise

    # ── statements ────────────────────────────────────────────

    def insert(self, query: str, params: Sequence[Any] = ()) -> None:
        """Execute one write. Not committed until :meth:`commit`."""
        self.ensure_connection()
        self._dirty = True
        with self.conn.cursor() as cur:
            cur.execute(query, params)

    def insert_many(
        self,
        query: str,
        rows: Sequence[Sequence[Any]],
        page_size: int = 500,
    ) -> int:
        """Execute one write per row, batched into few round trips.

        Over the internet to Azure a round trip costs 20-60 ms, so a per-row
        loop over the CBS data spends most of an hour waiting. ``execute_batch``
        collapses ``page_size`` statements into a single send, which is the
        difference between minutes and seconds.

        Returns the number of rows sent.
        """
        if not rows:
            return 0
        self.ensure_connection()
        self._dirty = True
        with self.conn.cursor() as cur:
            extras.execute_batch(cur, query, rows, page_size=page_size)
        return len(rows)

    def fetch(
        self, query: str, params: Sequence[Any] | Mapping[str, Any] = (),
    ) -> list[dict[str, Any]]:
        """Run a read and return every row as a dict."""
        self.ensure_connection()
        with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def fetch_one(
        self, query: str, params: Sequence[Any] | Mapping[str, Any] = (),
    ) -> dict[str, Any] | None:
        """Run a read and return the first row, or None."""
        self.ensure_connection()
        with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()

    def query(self, name: str, **params: Any) -> list[dict[str, Any]]:
        """Run a registered read query (``src/db/sql/queries.sql``) by name.

        Each ``$name`` placeholder in the registry becomes a psycopg2 named
        parameter (``%(name)s``), so every placeholder the query uses must be
        passed as a keyword argument here — pass ``None`` explicitly for an
        ``IS NULL OR ...``-style optional filter, since presence is all that's
        checked, not truthiness.
        """
        spec = self.queries.get(name)
        if spec is None:
            raise KeyError(f"No registered query named {name!r}")
        missing = [p for p in spec["params"] if p not in params]
        if missing:
            raise ValueError(f"Query {name!r} is missing required params: {missing}")
        sql = _PARAM_RE.sub(lambda m: f"%({m.group(1)})s", spec["query"])
        return self.fetch(sql, params)


# ──────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────

def table_counts(client: DBClient, tables: Sequence[str]) -> dict[str, int]:
    """Row count per table; 0 for a table that does not exist yet.

    Used by ingestion steps to report their before/after effect without
    assuming every table's schema has already landed. A pipeline step and
    the rich CLI both call this on the same client, then render the result
    their own way — plain text or a Rich table.
    """
    present = {
        row["table_name"]
        for row in client.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    }
    counts: dict[str, int] = {}
    for table in tables:
        counts[table] = (
            client.fetch_one(f"SELECT count(*) AS n FROM {table}")["n"]
            if table in present else 0
        )
    return counts


# ──────────────────────────────────────────────────────────────
# Smoke test
# ──────────────────────────────────────────────────────────────

_GRAPH_TABLES = [
    "gemeente_nodes", "wijk_nodes", "buurt_nodes", "question",
    "report_nodes", "chunk_nodes", "chunk_answer_nodes", "area_nodes",
]


def _check(ensure_schema: bool) -> int:
    dsn = resolve_dsn()
    print(f"connecting to {describe_dsn(dsn)}")

    client = DBClient(ensure_schema=ensure_schema)
    try:
        server = client.fetch_one("SELECT version() AS version")
        print(f"connected  {server['version'].split(',')[0]}")

        tls = client.fetch_one(
            "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        )
        if tls:
            print(f"tls        {'on ' + (tls['version'] or '') if tls['ssl'] else 'OFF'}")

        present = {
            row["table_name"]
            for row in client.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        }
        print("tables")
        for table in _GRAPH_TABLES:
            if table not in present:
                print(f"  {table:<20} absent")
                continue
            count = client.fetch_one(f"SELECT count(*) AS n FROM {table}")["n"]
            print(f"  {table:<20} {count:>8,}")
    finally:
        client.close()
    return 0


def main() -> int:
    safe_console()
    parser = argparse.ArgumentParser(description="Check the database connection.")
    parser.add_argument(
        "--no-schema",
        action="store_true",
        help="do not create missing tables while checking",
    )
    args = parser.parse_args()
    try:
        return _check(ensure_schema=not args.no_schema)
    except (RuntimeError, ConnectionError) as exc:
        print(f"\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
