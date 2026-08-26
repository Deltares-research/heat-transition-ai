from __future__ import annotations
import os
import re
import unicodedata
from pathlib import Path
import pandas as pd
import yaml
from dotenv import load_dotenv
from src import DBClient, clean, parse_response, ingest_gemeentes, ingest_questions


ALIASES = {
    "den haag": "s gravenhage",
    "den bosch": "s hertogenbosch",
}

MODALITIES = {
    "vastgesteld", "voornemen", "verkenning",
    "expliciet_geen", "onduidelijk", "niet_vermeld",
}

load_dotenv(Path(__file__).parents[1] / ".env")
DB_NAME = os.environ.get("DB_NAME", "nplw")
LANGUAGE = os.environ.get("LANGUAGE", "en")


def norm(s: str) -> str:
    """Normalise a municipality name to a join key."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "").replace("-", " ")
    s = re.sub(r"\(gemeente\)", "", s)
    s = re.sub(r"\((nh|l|ov|fr|gld|nb|zh|ut|dr|gr)\.?\)", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)


if __name__ == "__main__":

    data_path = Path(__file__).parents[1] / "data"

    client = DBClient()

    # insert_gemeentes(client, data_path/"buurt_data.jsonl")

    ingest_questions(client, data_path / "input/questions.yaml")

    # qs = yaml.safe_load((data_path / "input/questions.yaml").read_text(encoding="utf-8"))
    # QTYPES = {q["id"]: q["type"] for q in qs}

    # db.conn.executemany(
    #     """
    #     INSERT OR REPLACE INTO question (id, section, type, values, nl, en, ord)
    #     VALUES (?, ?, ?, ?, ?, ?, ?)
    #     """,
    #     [(q["id"], q.get("section"), q["type"], q.get("values"), q["nl"], q["en"], i)
    #      for i, q in enumerate(qs)],
    # )
    # print(f"questions: {len(qs)}")
    #
    # df_gem = pd.read_json(data_path / "gemeente_data.jsonl", lines=True)
    # df_gem["key"] = df_gem["gemeente"].map(norm)
    #
    # df_docs = pd.read_json(data_path / "data.jsonl", lines=True)
    # df_docs["key"] = df_docs["municipality"].map(norm)
    #
    # df_resp = pd.read_json(data_path / f"responses_{LANGUAGE}.jsonl", lines=True)
    #
    # # Documents whose municipality name matches nothing in the CBS list:
    # # typos in the source list, or names needing an ALIASES entry.
    # unmatched = df_docs.loc[~df_docs["key"].isin(set(df_gem["key"])), "municipality"]
    # if len(unmatched):
    #     print(f"WARNING: {len(unmatched)} documents matched no municipality: "
    #           f"{sorted(unmatched.tolist())}")
    #
    # n_resp = 0
    # for _, row in df_gem.iterrows():
    #
    #     doc = df_docs.loc[df_docs["key"] == row["key"]]
    #     d = doc.iloc[0] if not doc.empty else None
    #
    #     # Every municipality goes in, with or without a programme — the
    #     # nulls are what make the coverage gap queryable.
    #     db.insert_gemeente([clean(v) for v in [
    #         row["gemeente"],
    #         row["gemeentecode"],
    #         d["province"]     if d is not None else None,
    #         d["region"]       if d is not None else None,
    #         d["number_users"] if d is not None else None,
    #         d["url"]          if d is not None else None,
    #         d["chars"]        if d is not None else None,
    #     ]])
    #
    #     if d is None:
    #         continue
    #
    #     for _, r in df_resp.loc[df_resp["doc_id"] == d["id"]].iterrows():
    #         modality = clean(r.get("modality"))
    #         qtype = QTYPES.get(r["question_id"], "text")
    #
    #         db.insert_response({
    #             "gemeentecode": row["gemeentecode"],
    #             "question_id": r["question_id"],
    #             "doc_id": d["id"],
    #             "response": clean(r.get("response")),
    #             "modality": modality if modality in MODALITIES else None,
    #             "ref": r.get("ref"),
    #             "page": r.get("page"),
    #             "note": r.get("note"),
    #             "lang": LANGUAGE,
    #             **parse_response(r.get("response"), qtype),
    #         })
    #         n_resp += 1
    #
    # total = db.fetch("SELECT count(*) FROM gemeente")[0][0]
    # without = db.fetch("SELECT count(*) FROM gemeente WHERE url IS NULL")[0][0]
    # print(f"gemeenten: {total} ({without} without a programme)")
    # print(f"responses: {n_resp}")
    # print(db.fetch("SELECT modality, count(*) FROM response GROUP BY 1 ORDER BY 2 DESC"))
    #
    # db.close()

