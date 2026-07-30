import os

import pandas as pd
from pathlib import Path
import json
import yaml
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parents[1]/".env")
LANGUAGE = os.environ.get("LANGUAGE", "en")

def load_questions(path: Path) -> list[dict]:
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise ValueError(f"expected a list of questions, got {type(questions).__name__}")
    return questions


if __name__ == "__main__":

    root = Path(__file__).parents[1]
    data_path = root / "data"

    questions_path = root / "questions.yaml"
    questions = load_questions(questions_path)

    with open(data_path / "data.jsonl", "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f if line.strip()]

    with open(data_path / f"responses_{LANGUAGE}.jsonl", "r", encoding="utf-8") as f:
        responses = [json.loads(line) for line in f if line.strip()]

    for i_row, data_row in enumerate(data):

        rows_responses = [resp for resp in responses if resp["doc_id"] == data_row["id"]]

        response = None
        for question in questions:
            for row in rows_responses:
                if row["question_id"] == question["id"]:
                    response = row["response"]
            data_row[question[LANGUAGE]] = response

        data[i_row] = data_row

    df = pd.DataFrame.from_records(data)
    df.to_excel(data_path/f"responses_{LANGUAGE}.xlsx", index=False)
