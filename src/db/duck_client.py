import re
from pathlib import Path
import duckdb
from src.db.utils import *


SCHEMA_PATH = Path(__file__).parent / "sql/schema.sql"
QUERIES_PATH = Path(__file__).parent / "sql/queries.sql"


INSERT_GEMEENTE = """
            INSERT OR REPLACE INTO gemeente
            (gemeente, gemeentecode, province, region, number_users, url, chars)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """

INSERT_RESPONSE = """
            INSERT OR REPLACE INTO response
            (gemeentecode, question_id, doc_id, response, modality, ref, page, note, lang)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """


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


class DuckClient:

    def __init__(self, db_path: Path | str):

        if not isinstance(db_path, Path):
            db_path = Path(db_path)

        self.conn = duckdb.connect(str(db_path))
        self.conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.queries = load_queries()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def run(self, query: str, params: list | tuple | None = None, insert: bool = False):
        if insert:
            return self.conn.execute(query, params or [])
        else:
            return self.conn.execute(query, params or []).fetchall()

    def insert_gemeente(self, params: list | tuple):
        self.run(INSERT_GEMEENTE, params, insert=True)

    def insert_response(self, row: dict):
        cols = ", ".join(row)
        marks = ", ".join("?" * len(row))
        self.conn.execute(
            f"INSERT OR REPLACE INTO response ({cols}) VALUES ({marks})",
            [clean(v) for v in row.values()],
        )

    def fetch(self, query: str, params: list | tuple | None = None):
        return self.run(query, params, insert=False)

    def describe_queries(self) -> list[dict]:
        """Catalog for tool registration: name, description, use_when, params."""
        return [{"name": n, **{k: v for k, v in q.items() if k != "query"}}
                for n, q in self.queries.items()]

    def query(self, name: str, **params):
        """
        Run a named query from queries.sql. DataFrame out.

            db.query("who_answered", question_id="waterstof_status", pattern="%warmtenet%")
        """
        if name not in self.queries:
            raise KeyError(f"unknown query {name!r}. Available: {sorted(self.queries)}")

        spec = self.queries[name]
        missing = set(spec["params"]) - set(params)
        if missing:
            raise ValueError(f"{name} needs {sorted(missing)}")

        sql = spec["query"]
        values = []
        for placeholder in re.findall(r"\$(\w+)", sql):
            values.append(clean(params[placeholder]))
        sql = re.sub(r"\$\w+", "?", sql)

        return self.conn.execute(sql, values).fetchall()


if __name__ == "__main__":

    pass
