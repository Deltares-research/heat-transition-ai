from __future__ import annotations
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm
import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False

load_dotenv(Path(__file__).parents[1] / ".env")


MODEL    = os.environ.get("EMBED_MODEL", "text-embedding-3-large")
API_KEY  = os.environ.get("API_KEY")
API_BASE = os.environ.get("API_BASE")
BATCH    = int(os.environ.get("EMBED_BATCH", "100"))


def embed(texts: list[str]) -> list[list[float]]:
    resp = litellm.embedding(
        model=MODEL, input=texts,
        api_key=API_KEY, api_base=API_BASE,
    )
    return [d["embedding"] for d in resp.data]


if __name__ == "__main__":

    chunks_path = Path(__file__).parents[1] / "data/processed/chunks.jsonl"
    out_path = Path(__file__).parents[1] / "data/processed/chunks_embedded.jsonl"

    chunks = [json.loads(l) for l in chunks_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    with out_path.open("a", encoding="utf-8") as fh:
        for i in tqdm(range(0, len(chunks), BATCH)):
            batch  = chunks[i:i + BATCH]
            texts  = [c["text"] for c in batch]
            vecs   = embed(texts)
            for chunk, vec in zip(batch, vecs):
                chunk["embedding"] = vec
                fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")