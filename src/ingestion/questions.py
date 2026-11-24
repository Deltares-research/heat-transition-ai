from pathlib import Path

import yaml

from src.db.db_client import DBClient


def ingest_questions(client: DBClient, questions_path: Path | str) -> None:

    if not isinstance(questions_path, Path):
        questions_path = Path(questions_path)

    qs = yaml.safe_load(questions_path.read_text(encoding="utf-8"))

    rows = [
        (
            q["id"],
            q.get("section"),
            q["type"],
            q.get("values"),
            q["nl"],
            q["en"],
            i,
            q.get("origin"),
        )
        for i, q in enumerate(qs)
    ]

    with client.transaction():
        client.insert_many(client.inserts["insert_question"]["query"], rows)

    print(f"Ingested {len(rows)} questions")




if __name__ == "__main__":

    pass

