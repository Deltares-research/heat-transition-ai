import os
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from src.db.utils import *

load_dotenv(Path(__file__).parents[2]/"secrets/db.env")


NODES_PATH = Path(__file__).parent / "sql/nodes.sql"
EDGES_PATH = Path(__file__).parent / "sql/edges.sql"
INSERTS_PATH = Path(__file__).parent / "sql/inserts.sql"
QUERIES_PATH = Path(__file__).parent / "sql/queries.sql"


def load_queries(path: Path = QUERIES_PATH) -> dict[str, dict]:

    queries = {}

    for chunk in path.read_text(encoding="utf-8").split("-- name: ")[1:]:
        lines = chunk.splitlines()
        name = lines[0].strip()

        meta = {}
        body = []
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("--"):
                if body:
                    continue
                m = re.match(r"--\s*(description|use when|params)\s*:\s*(.*)",
                             stripped, flags=re.I)
                if m:
                    meta[m.group(1).lower().replace(" ", "_")] = m.group(2).strip()
                continue
            if stripped:
                body.append(line)

        sql = "\n".join(body).strip().rstrip(";")
        if not sql:
            continue

        queries[name] = {
            "description": meta.get("description", ""),
            "use_when": meta.get("use_when", ""),
            "query": sql,
            "params": sorted(set(re.findall(r"\$(\w+)", sql))),
        }

    return queries


def load_inserts(path: Path =  INSERTS_PATH) -> dict[str, dict]:

    inserts = {}

    for chunk in path.read_text(encoding="utf-8").split("-- name: ")[1:]:
        lines = chunk.splitlines()
        name = lines[0].strip()

        meta = {}
        body = []
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("--"):
                if body:
                    continue
                m = re.match(r"--\s*(description|use when|params)\s*:\s*(.*)",
                             stripped, flags=re.I)
                if m:
                    meta[m.group(1).lower().replace(" ", "_")] = m.group(2).strip()
                continue
            if stripped:
                body.append(line)

        sql = "\n".join(body).strip().rstrip(";")
        if not sql:
            continue

        inserts[name] = {
            "query": sql,
            "params": sorted(set(re.findall(r"\$(\w+)", sql))),
        }

    return inserts


class DBClient:

    def __init__(self, readonly: bool = False):
        self.readonly = readonly
        self.connect()
        self.load_query_registry()
        if not self.readonly:
            self.ensure_schema()
        if self.readonly:
            self.conn.set_session(readonly=True, autocommit=True)

    def connect(self) -> None:
        self.db_url = os.environ.get("DB_URL", "dbname=nplw")
        self.conn = psycopg2.connect(self.db_url)

    def ensure_schema(self) -> None:
        """Create tables and indices if they don't exist. Safe to call multiple times."""
        with self.conn.cursor() as cur:
            cur.execute(NODES_PATH.read_text(encoding="utf-8"))
            cur.execute(EDGES_PATH.read_text(encoding="utf-8"))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def load_query_registry(self) -> None:
        self.inserts = load_inserts()
        self.queries = load_queries()

    def __enter__(self) -> "Client":
        self.connect()
        self.load_query_registry()
        if not self.readonly:
            self.ensure_schema()
        if self.readonly:
            self.conn.set_session(readonly=True, autocommit=True)
        return self

    def __exit__(self, *exc):
        self.close()

    def insert(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self.conn.cursor() as cur:
            cur.execute(query, params)

    def fetch(self, query: str, params: tuple[Any, ...] = ()) -> list:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            data = cur.fetchall()
        return data




if __name__ == "__main__":

    pass
