from pathlib import Path
import json
from src.db.db_client import DBClient
import math
import yaml
from tqdm import tqdm

def ingest_questions(client: DBClient, questions_path: Path | str) -> None:

    if not isinstance(questions_path, Path):
        questions_path = Path(questions_path)

    qs = yaml.safe_load(questions_path.read_text(encoding="utf-8"))

    for i, q in enumerate(tqdm(qs, desc="Ingesting questions")):
        client.insert(
            client.inserts["insert_question"]["query"],
            (
                q["id"],
                q.get("section"),
                q["type"],
                q.get("values"),
                q["nl"],
                q["en"],
                i,
                q.get("origin"),
            ),
        )




if __name__ == "__main__":

    pass

